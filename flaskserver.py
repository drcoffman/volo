import uuid
import os
import atexit
import signal
import subprocess
import time
from flask import Flask, request, jsonify, Response, stream_with_context, render_template
from flask_cors import CORS
from bs4 import BeautifulSoup
import requests
import json
import configparser
import glob
import re
app = Flask(__name__)
CORS(app)
# Define the path to the config file
CONFIG_FILE_PATH =  'config.ini'
# Default configuration values
# download location: https://download.kiwix.org/zim/wikipedia/wikipedia_en_all_nopic_2024-06.zim
import platform

# Determine the operating system
os_type = platform.system().lower()

# Set the appropriate path based on the operating system
if os_type == 'windows':
    kiwix_tools_path = 'kiwix-tools-win-i686-3.7.0-2'
elif os_type == 'linux':
    kiwix_tools_path = 'kiwix-tools-linux-x86_64-3.7.0-2'
else:  # Default to macOS if not Windows or Linux
    kiwix_tools_path = 'kiwix-tools-macos-arm64-3.7.0-2'

 # Very simple stopword list for heading–query overlap scoring
STOPWORDS = {
    "the", "a", "an", "in", "on", "of", "for", "to", "and",
    "is", "are", "was", "were", "when", "what", "where", "why",
    "how", "best", "time", "year", "north", "south", "east",
    "west", "america", "american", "about", "from"
}

def score_heading_for_query(heading: str, query: str) -> int:
    """Score how well a heading matches the query based on word overlap."""
    q_terms = {
        w for w in re.findall(r"\w+", query.lower())
        if w not in STOPWORDS
    }
    h_terms = set(re.findall(r"\w+", heading.lower()))
    return len(q_terms & h_terms)

def filter_and_order_headings(selected_headings, query, min_overlap=1, max_k=3):
    """
    Re-rank and optionally filter headings so they match the query better.

    - Prefer headings that share non-trivial words with the query.
    - Drop headings with zero overlap if we still have at least one that matches.
    """
    if not selected_headings:
        return []

    # Score each heading
    scored = [(score_heading_for_query(h, query), h) for h in selected_headings]

    # Keep only headings with some overlap
    filtered = [h for s, h in scored if s >= min_overlap]

    # If filtering removed everything, fall back to original list
    if not filtered:
        filtered = [h for _, h in scored]

    # Re-score (in case we changed the list) and sort by score descending
    filtered_scored = sorted(
        ((score_heading_for_query(h, query), h) for h in filtered),
        key=lambda x: x[0],
        reverse=True,
    )

    ordered = [h for _, h in filtered_scored]
    return ordered[:max_k]


def dedupe_preserve_order(seq):
    """Remove duplicates while preserving order."""
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

DEFAULT_CONFIG = {
    'PATHS': {
        'KIWIX_SEARCH_PATH': os.path.join(os.path.dirname(os.path.dirname(__file__)), 'volo', 'kiwix_tools', kiwix_tools_path, 'kiwix-search'),
        'KIWIX_SERVE_PATH': os.path.join(os.path.dirname(os.path.dirname(__file__)), 'volo', 'kiwix_tools', kiwix_tools_path, 'kiwix-serve'),
        'ZIM_FILE_PATH': os.path.join(os.path.dirname(os.path.dirname(__file__)), 'volo', 'database', 'Wikipedia', 'wikipedia_en_all_nopic_2024-06.zim')
    },
    'SERVER': {
        'PORT': '1255',
        'KIWIX_SERVE_URL': 'http://localhost:821',
        'HEADING_COUNT': '64',
        'AI_MODEL': 'qwen2.5:3b',
        'OLLAMA_API_URL': 'http://localhost:11434/api/chat'
        #'API_KEY': 'support-for-custom-api-providers-is-currently-unavailable'
    }
}
def load_config():
    """Load configuration from file or create it with default values if missing or damaged."""
    config = configparser.ConfigParser()
    if not os.path.exists(CONFIG_FILE_PATH):
        print("Config file not found, creating with default values...")
        config.read_dict(DEFAULT_CONFIG)
        with open(CONFIG_FILE_PATH, 'w') as configfile:
            config.write(configfile)
    else:
        try:
            config.read(CONFIG_FILE_PATH)
            # Validate the config file by checking if all required sections and options are present
            for section, options in DEFAULT_CONFIG.items():
                if not config.has_section(section):
                    raise configparser.Error(f"Missing section: {section}")
                for option in options:
                    if not config.has_option(section, option):
                        raise configparser.Error(f"Missing option: {section}.{option}")
        except (configparser.Error, ValueError) as e:
            print(f"Config file is damaged: {e}, regenerating with default values...")
            config.read_dict(DEFAULT_CONFIG)
            with open(CONFIG_FILE_PATH, 'w') as configfile:
                config.write(configfile)
    return config
# Load configuration
config = load_config()
# Assign configuration values to variables
KIWIX_SEARCH_PATH = config['PATHS']['KIWIX_SEARCH_PATH']
KIWIX_SERVE_PATH = config['PATHS']['KIWIX_SERVE_PATH']
ZIM_FILE_PATH = config['PATHS']['ZIM_FILE_PATH']
PORT = int(config['SERVER']['PORT'])
KIWIX_SERVE_URL = config['SERVER']['KIWIX_SERVE_URL']
HEADING_COUNT = int(config['SERVER']['HEADING_COUNT'])
AI_MODEL = config['SERVER']['AI_MODEL']
OLLAMA_API_URL = config['SERVER']['OLLAMA_API_URL']

# Log the AI model being used
print(f"AI Model loaded: {AI_MODEL}")
print(f"Ollama API URL: {OLLAMA_API_URL}")
#API_KEY = config['SERVER']['API_KEY']
API_KEY = 'support-for-custom-api-providers-is-currently-unavailable'
# Global variable to store the kiwix-serve process
kiwix_serve_process = None
# Define headers to be used in API calls
API_HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'Authorization': f'Bearer {API_KEY}'  # Ensure API_KEY is defined in your environment or code
}
def start_kiwix_serve():
    """Start the kiwix-serve process."""
    global kiwix_serve_process
    try:
        # Start the kiwix-serve process
        kiwix_serve_process = subprocess.Popen(
            [KIWIX_SERVE_PATH, ZIM_FILE_PATH, "-p", "821"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        print("kiwix-serve process started successfully.")
    except Exception as e:
        print(f"Failed to start kiwix-serve: {e}")
        raise
def stop_kiwix_serve():
    """Stop the kiwix-serve process."""
    global kiwix_serve_process
    if kiwix_serve_process:
        print("Stopping kiwix-serve process...")
        kiwix_serve_process.terminate()  # Send SIGTERM
        try:
            kiwix_serve_process.wait(timeout=5)  # Wait for the process to terminate
        except subprocess.TimeoutExpired:
            print("kiwix-serve process did not terminate gracefully, killing it...")
            kiwix_serve_process.kill()  # Force kill if it doesn't terminate
        print("kiwix-serve process stopped.")
# Register the stop_kiwix_serve function to run on app exit
atexit.register(stop_kiwix_serve)
# Handle termination signals (e.g., Ctrl+C)
def handle_signal(signum, frame):
    """Handle termination signals."""
    print(f"Received signal {signum}, stopping kiwix-serve...")
    stop_kiwix_serve()
    exit(0)
# Register signal handlers for graceful shutdown
signal.signal(signal.SIGINT, handle_signal)  # Ctrl+C
signal.signal(signal.SIGTERM, handle_signal)  # Termination signal
# Start kiwix-serve when the app starts
start_kiwix_serve()
# Function to perform a search using kiwix-search
def perform_search(query, zim_path=None):
    print(f"Searching for: {query}")
    
    # Use provided ZIM path or default
    if zim_path is None:
        zim_path = ZIM_FILE_PATH
    
    # Execute the kiwix-search command
    try:
        result = subprocess.run(
            [KIWIX_SEARCH_PATH, zim_path, query],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print(f"Error executing kiwix-search: {result.stderr}")
            return None
        # Extract the first n article headings from the output
        output_lines = result.stdout.splitlines()
        if not output_lines:
            print("No search results found.")
            return None
        # Filter out headings that contain the word "disambiguation"
        filtered_headings = [line.strip() for line in output_lines if "disambiguation" not in line.lower()]
        # Get the first 64 headings after filtering
        first_n_headings = filtered_headings[:HEADING_COUNT]
        print(f"First {HEADING_COUNT} headings after filtering: {first_n_headings}")
        return first_n_headings
    except Exception as e:
        print(f"Error during search: {e}")
        return None
# Function to select the best heading using the LLM
def select_best_heading(query, headings):
    print("Selecting the best heading...")

    if not headings:
        print("No headings provided to select_best_heading.")
        return None

    # Construct the headings string with newlines
    headings_str = "\n".join(headings)

    try:
        response = requests.post(
            OLLAMA_API_URL,
            headers=API_HEADERS,
            json={
                "model": AI_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a research assistant. From the list of headings provided, "
                            "select exactly ONE heading that is most relevant to the user's query.\n\n"
                            "CRITICAL RULES:\n"
                            "1. You MUST respond with the heading text ONLY.\n"
                            "2. Do NOT add quotes, explanations, or any other words.\n"
                            "3. The heading MUST be an exact copy of one of the provided headings.\n"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"The user's query is:\n{query}\n\n"
                            f"Here are the available headings (one per line):\n{headings_str}\n\n"
                            "Return ONLY the single best heading from this list."
                        ),
                    },
                ],
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_ctx": 2048,
                },
            },
            timeout=60,
        )
        response.raise_for_status()

        raw = response.json()["message"]["content"].strip()
        print(f"Raw best-heading response: {raw!r}")

        # Take the first line in case the model added extra lines
        candidate = raw.splitlines()[0].strip()

        # Strip surrounding quotes if present
        if (candidate.startswith('"') and candidate.endswith('"')) or (
            candidate.startswith("'") and candidate.endswith("'")
        ):
            candidate = candidate[1:-1].strip()

        # 1) Exact match
        if candidate in headings:
            print(f"Selected best heading (exact match): {candidate}")
            return candidate

        # 2) Case-insensitive match
        lower_candidate = candidate.lower()
        for h in headings:
            if h.lower() == lower_candidate:
                print(f"Selected best heading (case-insensitive match): {h}")
                return h

        # 3) Substring match as last resort
        for h in headings:
            if h in raw:
                print(f"Selected best heading (substring match): {h}")
                return h

        # If we get here, we couldn't map the model output to a known heading
        print("Could not match model output to any heading; falling back to first heading.")
        return headings[0]

    except Exception as e:
        print(f"Error selecting best heading: {e}")
        # Fallback: return first heading
        return headings[0]


# Function to select the top 3 most relevant headings using the LLM
def select_top_3_headings(query, headings):
    print("Selecting the top 3 most relevant headings...")

    headings_str = "\n".join(headings)

    try:
        response = requests.post(
            OLLAMA_API_URL,
            headers=API_HEADERS,
            json={
                "model": AI_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a research assistant. Your task is to select the 3 most relevant "
                            "headings from the list provided based on the user's query.\n\n"
                            "CRITICAL RULES:\n"
                            "1. You MUST respond ONLY with a JSON array of strings.\n"
                            '   Example: ["heading1", "heading2", "heading3"]\n'
                            "2. Do NOT include any explanation, commentary, or other text.\n"
                            "3. Every string in the array MUST exactly match one of the headings provided.\n"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"The user's query is:\n{query}\n\n"
                            f"Here are the headings (one per line):\n{headings_str}\n\n"
                            "Return ONLY a JSON array like:\n"
                            '["heading1", "heading2", "heading3"]\n'
                        ),
                    },
                ],
                "stream": False,
                "options": {
                    "temperature": 0.48,
                    "num_ctx": 2048,
                },
            },
        )
        response.raise_for_status()

        raw = response.json()["message"]["content"].strip()
        print(f"Selected headings raw response: {raw}")

        import json

        # First try: assume the model actually obeyed and gave pure JSON
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Fallback: try to extract the JSON array from within extra text
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start == -1 or end <= start:
                raise  # will be caught by outer except

            json_fragment = raw[start:end]
            print(f"Extracted JSON fragment: {json_fragment}")
            parsed = json.loads(json_fragment)

        # Ensure it's a list of strings
        if not isinstance(parsed, list):
            raise ValueError("Parsed headings are not a list")

        parsed = [str(h).strip() for h in parsed]

        # Filter to only headings actually returned by kiwix-search
        # and keep order as given by the model
        headings_set = set(headings)
        selected_headings = [h for h in parsed if h in headings_set][:3]

        if not selected_headings:
            raise ValueError("No valid headings selected from the model output")

        print(f"Top 3 headings: {selected_headings}")
        return selected_headings

    except Exception as e:
        print(f"Error selecting top 3 headings: {e}")
        # Fallback: just take the first 3 headings from kiwix-search
        return headings[:3]

# Function to get ZIM file name without extension
def get_zim_file_name(zim_path=None):
    """Extract the ZIM file name without extension from the full path."""
    import os
    if zim_path is None:
        zim_path = ZIM_FILE_PATH
    return os.path.splitext(os.path.basename(zim_path))[0]

# Function to list available ZIM files in a directory
def list_zim_files(directory_path):
    """List all .zim files in the specified directory and subdirectories."""
    zim_files = []
    try:
        # Search for .zim files recursively
        pattern = os.path.join(directory_path, "**", "*.zim")
        found_files = glob.glob(pattern, recursive=True)
        
        for file_path in found_files:
            file_info = {
                'path': file_path,
                'name': os.path.basename(file_path),
                'size': os.path.getsize(file_path),
                'relative_path': os.path.relpath(file_path, directory_path)
            }
            zim_files.append(file_info)
        
        # Sort by name
        zim_files.sort(key=lambda x: x['name'])
        
    except Exception as e:
        print(f"Error listing ZIM files: {e}")
    
    return zim_files

# Function to restart kiwix-serve with a new ZIM file
def restart_kiwix_serve_with_zim(zim_file_path):
    """Stop current kiwix-serve and start it with a new ZIM file."""
    global kiwix_serve_process, ZIM_FILE_PATH
    
    # Stop current process
    stop_kiwix_serve()
    
    # Update the ZIM file path
    ZIM_FILE_PATH = zim_file_path
    
    # Start with new ZIM file
    start_kiwix_serve()
    
    return True

# Function to fetch article content from Kiwix server
def fetch_article_content(heading, zim_path=None):
    # Replace spaces with underscores
    formatted_heading = heading.replace(" ", "_")
    
    # Get the ZIM file name dynamically
    zim_name = get_zim_file_name(zim_path)
    
    # Construct the URL
    article_url = f"{KIWIX_SERVE_URL}/{zim_name}/A/{formatted_heading}"
    print(f"Fetching article from: {article_url}")
    try:
        # Fetch the HTML content
        response = requests.get(article_url, headers=API_HEADERS)
        response.raise_for_status()  # Raise an error for bad status codes
        # Parse the HTML using BeautifulSoup
        soup = BeautifulSoup(response.text, "html.parser")
        # Extract readable text from the article
        article_text = soup.get_text(separator="\n", strip=True)
        return article_text, article_url
    except requests.exceptions.RequestException as e:
        print(f"Error fetching article content: {e}")
        return None, None

# Function to fetch multiple articles and return combined content with citations
def fetch_multiple_articles(headings, zim_path=None):
    print(f"Fetching content for {len(headings)} articles...")
    
    articles_data = []
    combined_content = ""
    citations = []
    
    for i, heading in enumerate(headings, 1):
        print(f"Fetching article {i}/{len(headings)}: {heading}")
        article_content, article_url = fetch_article_content(heading, zim_path)
        
        if article_content and article_url:
            articles_data.append({
                'heading': heading,
                'content': article_content,
                'url': article_url
            })
            
            # Add article to combined content with clear separation
            combined_content += f"\n\n=== ARTICLE {i}: {heading} ===\n\n"
            combined_content += article_content
            
            # Create citation
            citation = f"[Source {i}: {heading}]({article_url})"
            citations.append(citation)
        else:
            print(f"Failed to fetch article: {heading}")
    
    return articles_data, combined_content, citations

# ZIM file selection endpoints
@app.route("/zim", methods=["GET"])
def zim_selector_page():
    """Serve the ZIM file selection page."""
    return render_template('zim_selector.html')

@app.route("/zim/list", methods=["GET"])
def list_zim_files_route():
    """List available ZIM files in a directory."""
    directory_path = request.args.get('directory', '/Users/drcoffman/code/zim')
    
    if not os.path.exists(directory_path):
        return jsonify({"error": "Directory does not exist"}), 400
    
    zim_files = list_zim_files(directory_path)
    return jsonify({
        "directory": directory_path,
        "zim_files": zim_files,
        "count": len(zim_files)
    })

@app.route("/zim/select", methods=["POST"])
def select_zim_file():
    """Select and switch to a new ZIM file."""
    data = request.json or {}
    zim_file_path = data.get("zim_file_path")
    
    if not zim_file_path:
        return jsonify({"error": "zim_file_path is required"}), 400
    
    if not os.path.exists(zim_file_path):
        return jsonify({"error": "ZIM file does not exist"}), 400
    
    try:
        # Restart kiwix-serve with the new ZIM file
        restart_kiwix_serve_with_zim(zim_file_path)
        
        # Update the config file with the new path
        config.set('PATHS', 'ZIM_FILE_PATH', zim_file_path)
        with open(CONFIG_FILE_PATH, 'w') as configfile:
            config.write(configfile)
        
        return jsonify({
            "message": "ZIM file switched successfully",
            "zim_file_path": zim_file_path,
            "zim_name": get_zim_file_name(zim_file_path)
        })
    except Exception as e:
        return jsonify({"error": f"Failed to switch ZIM file: {str(e)}"}), 500

@app.route("/zim/current", methods=["GET"])
def get_current_zim():
    """Get information about the currently loaded ZIM file."""
    return jsonify({
        "zim_file_path": ZIM_FILE_PATH,
        "zim_name": get_zim_file_name(),
        "exists": os.path.exists(ZIM_FILE_PATH)
    })

# Search endpoint
@app.route("/search", methods=["POST"])
def search():
    data = request.json or {}
    query = data.get("query")
    context = data.get("context", [])
    try:
        # Step 1: Use Ollama with tool calling to generate four distinct search queries
        response = requests.post(
            OLLAMA_API_URL,
            headers=API_HEADERS,
            json={
                "model": AI_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a research assistant. "
                            "Use the search_engine tool to generate four distinct search queries "
                            "that will help gather a broad range of information related to the user's query. "
                            "Each query should focus on a different aspect or angle of the topic."
                        ),
                    },
                    *context,
                    {"role": "user", "content": query},
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "search_engine",
                            "description": (
                                "A Wikipedia search engine. Generate four distinct search queries "
                                "to maximize the spread of search results."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "queries": {
                                        "type": "array",
                                        "items": {
                                            "type": "string",
                                            "description": (
                                                "A distinct search query focusing on a "
                                                "specific aspect of the topic."
                                            ),
                                        },
                                        "minItems": 4,
                                        "maxItems": 4,
                                        "description": (
                                            "Four distinct search queries to maximize "
                                            "the spread of search results."
                                        ),
                                    },
                                },
                                "required": ["queries"],
                            },
                        },
                    },
                ],
                "stream": False,
                "options": {
                    "temperature": 0.48,
                    "num_ctx": 32768,
                },
            },
        )
        response.raise_for_status()
        tool_calls = response.json().get("message", {}).get("tool_calls", [])
        if tool_calls:
            print(f"Tool calls: {tool_calls}")
            tool_call = tool_calls[0]
            if tool_call["function"]["name"] == "search_engine":
                # Access the arguments directly (it's already a dictionary)
                arguments = tool_call["function"]["arguments"]
                search_queries = arguments.get("queries", []) or []
                print(f"Generated search queries (from tool): {search_queries}")

                # --- NEW: ensure the original user query is also searched, and dedupe ---
                if query:
                    # Prepend the original question so it has priority
                    combined_queries = [query] + search_queries
                else:
                    combined_queries = search_queries

                search_queries = dedupe_preserve_order(combined_queries)
                print(f"Final search queries after adding original query & dedupe: {search_queries}")
                # -----------------------------------------------------------------------

                # Step 2: Perform searches for each query and aggregate the results
                all_headings = []
                for search_query in search_queries:
                    first_n_headings = perform_search(search_query)
                    if first_n_headings:
                        all_headings.extend(first_n_headings)

                if not all_headings:
                    return jsonify({"message": "No search results found."})

                # Step 3: Select the top 3 most relevant headings using the LLM
                top_3_headings = select_top_3_headings(query, all_headings)
                if not top_3_headings:
                    return "No search results found."

                # --- NEW: re-rank/filter headings to stay on-topic w.r.t. the query ---
                top_3_headings = filter_and_order_headings(
                    top_3_headings,
                    query=query or "",
                    min_overlap=1,
                    max_k=3,
                )
                print(f"Top headings after filter_and_order_headings: {top_3_headings}")
                # ----------------------------------------------------------------------

                # Step 4: Fetch content for all 3 articles
                articles_data, combined_content, citations = fetch_multiple_articles(
                    top_3_headings
                )
                if not articles_data:
                    return (
                        "Failed to fetch article content. This can happen if the ZIM file path "
                        "is incorrect or if the AI made a mistake in selecting the headings."
                    )

                updated_context = context + [
                    {"role": "user", "content": query},
                    {
                        "role": "assistant",
                        "content": f"Search results from {len(articles_data)} articles: {combined_content}",
                    },
                ]

                # Step 5: Generate a detailed response based on the aggregated search results
                # Combine all citations
                all_citations = "\n".join(citations)
                print(f"Using {len(articles_data)} article URLs")
                print(f"All citations: {all_citations}")

                def generate_final_response():
                    # First, yield all citations
                    yield all_citations + "\n\n"

                    final_response = requests.post(
                        OLLAMA_API_URL,
                        json={
                            "model": AI_MODEL,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": f'''You are a precise question-answering assistant.

                                        You receive:
                                        - A user question.
                                        - A set of Wikipedia excerpts (plain text) that MAY or MAY NOT fully answer the question.

                                        Your priorities, in this order:

                                        1. ANSWER FROM THE EXCERPTS IF POSSIBLE.
                                        - Carefully read the excerpts and see whether they explicitly contain information that answers the question.
                                        - If they do, base your answer on those excerpts and say so (e.g., "According to the provided Wikipedia excerpts, ...").

                                        2. IF THE EXCERPTS DO NOT CLEARLY CONTAIN THE ANSWER:
                                        - First say explicitly that the provided excerpts do not clearly answer the question.
                                        - Then you MAY answer using your own general knowledge, but you MUST clearly label it, for example:
                                            "Based on general knowledge (not necessarily from the provided excerpts), ..."
                                        - Do NOT present general-knowledge content as if it definitely came from the excerpts.

                                        3. DIRECT ANSWER FIRST (2–5 sentences).
                                        - Always start with a direct answer to the user's question.
                                        - If the question is "How does X work?", give a step-by-step explanation of the mechanism or process.
                                        - If the question is "When is the best time to do X?" or "When did Y happen?", explicitly mention seasons/months or dates when that information is available.
                                        - If there are clearly multiple common variants of X described in the excerpts
                                            (for example, two-stroke and four-stroke internal combustion engines),
                                            briefly mention the existence of these variants and how they differ,
                                            even if you explain only one of them in detail.

                                        4. OPTIONAL DEEPER EXPLANATION.
                                        - After the direct answer, you may elaborate with more detail that helps the user understand the answer.
                                        - Keep this tightly focused on the user’s question.

                                        5. OPTIONAL CONTEXT / HISTORY.
                                        - Only after the main answer and deeper explanation, you may add historical or contextual information, but only if it is genuinely helpful.

                                        6. HANDLING "WHEN" / DATE / TIME QUESTIONS.
                                        - If the question is about a specific date, year, or time-of-year ("when did this happen?", "when is the best time to plant X?"):
                                            * If the excerpts do NOT clearly provide a specific date/season/month, treat the sources as insufficient for that part.
                                            * Do NOT invent or "infer" specific years or time ranges purely from vague context (e.g., "several centuries before 1325 BC") unless that range is explicitly supported by the excerpts.
                                            * If you use general knowledge to answer, clearly label it as such, as described above.

                                        7. IF THE SOURCES ARE INSUFFICIENT.
                                        - If the excerpts do not contain the needed facts, clearly state that they do not answer the question.
                                        - You may then provide a clearly labeled general-knowledge answer, or you may stop after stating that the excerpts are insufficient.
                                        - Do NOT pretend the excerpts contain information they do not.

                                        STRICTLY FORBIDDEN OUTPUT PATTERNS:
                                        - Do NOT structure your answer as "Article 1", "Article 2", "Key points", "Common themes", or "Differences".
                                        - Do NOT summarize each article separately.
                                        - Do NOT write a literature review.
                                        - Do NOT just list bullet points from the excerpts without actually answering the question.

                                        When the question includes words like "how", "why", "when", or "where", treat that word as the core of the task and structure your answer explicitly around it (e.g., "Here is how it works: ...", "Here is when it is typically done: ...").

                                        If the user’s question is about a specific topic mentioned by name (for example, "garlic"),
                                        your answer MUST stay focused on that topic. Do not switch to answering a different
                                        implicit question about a related concept (for example, generic plant stems) even if
                                        the excerpts contain more detailed information about that other concept.

                                        Use the Wikipedia excerpts as your primary evidence when they contain the answer. When they do not, it is acceptable to use your own world knowledge, but you MUST clearly label when you are doing so.

                                        Additional instructions: Enclose LaTeX math equations (if any) in $$.
                                        Example: $$x^2 + y^2 = z^2$$ and $$(E = mc^2)$$.''',
                                        },
                                        *updated_context,
                                        {
                                            "role": "user",
                                            "content": f'''User question:
                                        {query}

                                        You are given these excerpts from Wikipedia that may contain the answer
                                        (from {len(articles_data)} retrieved articles):

                                        {combined_content}

                                        Instructions recap:
                                        - First, try to answer from the excerpts. If they clearly contain the answer, base your response on them.
                                        - If the excerpts do NOT clearly contain the answer, say so explicitly, then (optionally) answer using your general knowledge, clearly labeled as such.
                                        - Start with a direct answer to the question, not a summary of each article.
                                        - Do NOT use headings like "Article 1", "Article 2", "Key points", "Common Themes", or "Differences".

                                        Now answer the user's question.''',
                                },
                            ],
                            "stream": True,
                            "options": {
                                "temperature": 0.48,
                                "num_ctx": 32768,
                            },
                        },
                        stream=True,
                    )
                    for chunk in final_response.iter_lines():
                        if chunk:
                            try:
                                # Parse the chunk as JSON
                                chunk_json = json.loads(chunk)
                                # Extract the content field
                                content = chunk_json.get("message", {}).get("content", "")
                                # Yield the content
                                yield content
                            except json.JSONDecodeError as e:
                                print(f"Error decoding JSON: {e}")
                                continue

                return Response(
                    stream_with_context(generate_final_response()),
                    content_type="text/plain",
                )

        # If no tool calls, return the response as a string
        return response.json()["message"]["content"]
    except Exception as e:
        print(f"Error: {e}")
        return (
            "An error occurred! This is most likely due to a connection issue with Ollama. "
            "Ensure that Ollama is running and that the model (default qwen2.5:3b) is available.",
            500,
        )


# OpenAI-compatible /models endpoint
@app.route("/v1/models", methods=["GET"])
def list_models():
    """Mimic the OpenAI /models endpoint."""
    return jsonify({
        "data": [
            {
                "id": "volo-workflow",
                "object": "model",
                "owned_by": "your-organization",
                "permission": []
            }
        ],
        "object": "list"
    })
# OpenAI-compatible /chat/completions endpoint
@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    data = request.json or {}
    # Extract the user's messages from the OpenAI-style request
    messages = data.get("messages", [])
    
    # Get the latest user message
    user_messages = [msg for msg in messages if msg["role"] == "user"]
    if not user_messages:
        return jsonify({
            "error": {
                "message": "No user message found in the request.",
                "type": "invalid_request_error",
                "code": 400
            }
        }), 400
    
    latest_user_message = user_messages[-1]["content"]  # Get the latest user message
    context = [msg for msg in messages if msg["role"] != "user"]  # All other messages as context

    # Prepare the request for the existing /search endpoint
    search_request = {
        "query": latest_user_message,
        "context": context  # Pass the context as expected by /search
    }
    # Forward the request to the /search logic
    try:
        # Make an HTTP request to the /search endpoint
        search_response = requests.post(f"http://localhost:{PORT}/search", json=search_request)
        # Check if the search response is valid
        if search_response.status_code != 200:
            return jsonify({
                "error": {
                    "message": "Search request failed.",
                    "type": "api_error",
                    "code": search_response.status_code
                }
            }), search_response.status_code
        # Extract the content from the search response
        content = search_response.text
        response = jsonify({
            "id": f"chatcmpl-{uuid.uuid4()}",  # Generate a unique ID
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "volo-workflow",  # Use the correct model name
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": len(latest_user_message.split()),  # Approximate token count
                "completion_tokens": len(content.split()),  # Approximate token count
                "total_tokens": len(latest_user_message.split()) + len(content.split())
            }
        })
        # Format the response according to OpenAI's API
        return response.get_json()
    except Exception as e:
        # Log the exception for debugging
        print(f"Error in /v1/chat/completions: {e}")
        return jsonify({
            "error": {
                "message": str(e),
                "type": "internal_server_error",
                "code": 500
            }
        }), 500
# Start the server
if __name__ == "__main__":
    try:
        app.run(host="0.0.0.0", port=PORT, debug=True)
    finally:
        # Ensure kiwix-serve is stopped when the app exits
        stop_kiwix_serve()