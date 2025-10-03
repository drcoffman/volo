import uuid
import os
import atexit
import signal
import subprocess
import time
import re
from flask import Flask, request, jsonify, Response, stream_with_context, render_template
from flask_cors import CORS
from bs4 import BeautifulSoup
import requests
import json
import configparser
import glob
import pprint as pp

def extract_json_from_text(text):
    """
    Extract JSON from text that may contain prefix and suffix content.
    Looks for JSON array or object patterns and extracts the first valid JSON found.
    """
    if not text:
        return None
    
    # Remove any markdown code block markers
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    
    # Look for JSON array pattern [ ... ]
    array_match = re.search(r'\[[^\]]*\]', text)
    if array_match:
        try:
            json_str = array_match.group(0)
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
    
    # Look for JSON object pattern { ... }
    object_match = re.search(r'\{[^}]*\}', text)
    if object_match:
        try:
            json_str = object_match.group(0)
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
    
    # If no pattern matches, try to parse the entire text
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return None

def exclude_references_section(html_content, verbose_debug=False):
    """
    Exclude content after the 'References' and 'Works Cited' sections from HTML content.
    Uses regular expressions to handle variations in HTML formatting.
    
    Args:
        html_content (str): The HTML content to process
        verbose_debug (bool): Whether to print debug information
    
    Returns:
        tuple: (cleaned_content, excluded_references)
    """
    if not html_content:
        return html_content, ""
    
    # Pattern to match References section with various HTML formatting variations
    # This pattern looks for:
    # - id="References" or id='References' or id = "References" etc.
    # - Can be in h1, h2, h3, h4, h5, h6, div, section, or other elements
    # - Handles various spacing and quote variations
    references_pattern = r'<[^>]*id\s*=\s*["\']References["\'][^>]*>.*?(?=<[^>]*id\s*=\s*["\'][^"\']*["\'][^>]*>|$)'
    
    # Pattern to match Works Cited section with various HTML formatting variations
    works_cited_pattern = r'<[^>]*id\s*=\s*["\']Works_cited["\'][^>]*>.*?(?=<[^>]*id\s*=\s*["\'][^"\']*["\'][^>]*>|$)'
    
    # Count occurrences of References sections
    references_count = len(re.findall(r'<[^>]*id\s*=\s*["\']References["\'][^>]*>', html_content, re.IGNORECASE))
    works_cited_count = len(re.findall(r'<[^>]*id\s*=\s*["\']Works_cited["\'][^>]*>', html_content, re.IGNORECASE))
    
    # Print warning if multiple References sections found
    if references_count > 1:
        print(f"\n⚠️  WARNING: Found {references_count} References sections. Some data may have been excluded.")
    
    if works_cited_count > 1:
        print(f"\n⚠️  WARNING: Found {works_cited_count} Works Cited sections. Some data may have been excluded.")
    
    # Find both sections
    references_match = re.search(references_pattern, html_content, re.IGNORECASE | re.DOTALL)
    works_cited_match = re.search(works_cited_pattern, html_content, re.IGNORECASE | re.DOTALL)
    
    # Determine which section comes first (if any)
    earliest_match = None
    excluded_references = ""
    
    if references_match and works_cited_match:
        if references_match.start() < works_cited_match.start():
            earliest_match = references_match
            excluded_references = html_content[references_match.start():]
        else:
            earliest_match = works_cited_match
            excluded_references = html_content[works_cited_match.start():]
    elif references_match:
        earliest_match = references_match
        excluded_references = html_content[references_match.start():]
    elif works_cited_match:
        earliest_match = works_cited_match
        excluded_references = html_content[works_cited_match.start():]
    
    if earliest_match:
        # Keep only the content before the earliest section
        cleaned_content = html_content[:earliest_match.start()]
        
        if verbose_debug:
            section_name = "References" if earliest_match == references_match else "Works Cited"
            print(f"\n=== EXCLUDED {section_name.upper()} SECTION ===")
            print(f"Excluded content length: {len(excluded_references)} characters")
            print(f"Cleaned content length: {len(cleaned_content)} characters")
            print("=" * 50)
        
        return cleaned_content, excluded_references
    else:
        if verbose_debug:
            print("\n=== NO REFERENCES OR WORKS CITED SECTION FOUND ===")
            print("No References or Works Cited section found in the content")
            print("=" * 50)
        
        return html_content, ""

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
print(f"🤖 AI Model loaded: {AI_MODEL}")
print(f"🔗 Ollama API URL: {OLLAMA_API_URL}")
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
    
    # Construct the headings string with newlines
    headings_str = '\n'.join(headings)
    
    try:
        response = requests.post(
            OLLAMA_API_URL,
            headers=API_HEADERS,
            json={
                "model": AI_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a research assistant. Your task is to select the most relevant heading from the list provided based on the user's query. Ensure the heading is in the list; avoid outputting headings that are not in the list."},
                    {"role": "user", "content": f"The user's query is: {query}. Here are the headings:\n{headings_str}\n\nPlease select the most relevant heading. Output the heading **only** and nothing else."},
                ],
                "stream": False,
                "options": {
                    "temperature": 0.48,
                    "num_ctx": 2048,
                }
            }
        )
        response.raise_for_status()
        selected_heading = response.json()["message"]["content"].strip()
        print(f"Selected heading: {selected_heading}")
        return selected_heading
    except Exception as e:
        print(f"Error selecting best heading: {e}")
        return None

# Function to select the top 3 most relevant headings using the LLM
def select_top_3_headings(query, headings):
    print("\n \n \n Selecting the top 3 most relevant headings...")
    
    # Construct the headings string with newlines
    headings_str = '\n'.join(headings)
    
    try:
        response = requests.post(
            OLLAMA_API_URL,
            headers=API_HEADERS,
            json={
                "model": AI_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a research assistant. Your task is to select the 3 most relevant headings from the list provided based on the user's query. Ensure all headings are in the provided list. You MUST respond with ONLY a valid JSON array. Do not include any explanatory text, markdown formatting, or other content. Only return the JSON array."},
                    {"role": "user", "content": f"The user's query is: {query}. Here are the headings:\n{headings_str}\n\nSelect the 3 most relevant headings and return ONLY a JSON array in this exact format: [\"heading1\", \"heading2\", \"heading3\"]\n\nIMPORTANT: Your response must contain ONLY the JSON array, nothing else."},
                ],
                "stream": False,
                "options": {
                    "temperature": 0.48,
                    "num_ctx": 2048,
                }
            }
        )
        response.raise_for_status()
        response_data = response.json()
        
        # Check if response has the expected structure
        if "message" not in response_data or "content" not in response_data["message"]:
            print("Error: Invalid response structure from AI model")
            return headings[:3]
            
        selected_headings_json = response_data["message"]["content"].strip()
        print(f"\n \n \n Selected headings JSON: {selected_headings_json}")
        
        # Check if response is empty
        if not selected_headings_json:
            print("Error: Empty response from AI model")
            return headings[:3]
        
        # Parse the JSON response using the extraction function
        selected_headings = extract_json_from_text(selected_headings_json)
        
        if selected_headings is None:
            print(f"Error: Could not extract valid JSON from response")
            print(f"Raw response: {selected_headings_json}")
            return headings[:3]
        
        # Validate that we got a list
        if not isinstance(selected_headings, list):
            print(f"Error: Expected list but got {type(selected_headings)}")
            return headings[:3]
        
        # Limit to 3 headings max
        selected_headings = selected_headings[:3]
        print(f"Top 3 headings: {selected_headings}")
        return selected_headings
    except Exception as e:
        print(f"Error selecting top 3 headings: {e}")
        # Fallback: return first 3 headings
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
    """List all .zim files in the specified directory only (no subdirectories)."""
    zim_files = []
    try:
        # Search for .zim files in the current directory only
        pattern = os.path.join(directory_path, "*.zim")
        found_files = glob.glob(pattern)
        
        for file_path in found_files:
            file_info = {
                'path': file_path,
                'name': os.path.basename(file_path),
                'size': os.path.getsize(file_path),
                'relative_path': os.path.basename(file_path)  # Just the filename since it's in the same directory
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
        
        # Ensure proper encoding
        response.encoding = 'utf-8'
        
        # Parse the HTML using BeautifulSoup
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Remove only truly noisy elements while preserving all semantic HTML structure
        for element in soup.find_all(['script', 'style', 'sup', 'sub']):
            element.decompose()
        
        # Convert to string while preserving HTML tags and creating flowing text
        article_text = str(soup)
        
        # Clean up excessive whitespace while preserving HTML structure
        import re
        # Replace multiple spaces with single space (but preserve HTML tag spacing)
        article_text = re.sub(r'[ ]{2,}', ' ', article_text)
        # Replace multiple newlines with single space to create flowing text
        article_text = re.sub(r'\n+', ' ', article_text)
        # Clean up any remaining formatting issues
        article_text = article_text.strip()
        
        # Exclude References section if VERBOSE_DEBUG is True
        VERBOSE_DEBUG = True  # Set to False for production
        cleaned_content, excluded_references = exclude_references_section(article_text, VERBOSE_DEBUG)
        
        if VERBOSE_DEBUG and excluded_references:
            print(f"\n=== EXCLUDED REFERENCES FOR ARTICLE: {heading} ===")
            print(f"Excluded content: {excluded_references[:500]}...")  # Show first 500 chars
            print("=" * 50)
        
        return cleaned_content, article_url
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
            citation = f"[📖 Source {i}: {heading}]({article_url})"
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
    
    # Debug configuration
    VERBOSE_DEBUG = True  # Set to False for production
    
    def debug_print(label, data, max_length=None):
        if VERBOSE_DEBUG:
            print(f"\n=== {label} ===")
            if max_length and isinstance(data, str) and len(data) > max_length:
                pp.pprint(data[:max_length] + "...", width=100)
            else:
                pp.pprint(data, width=100)
            print("=" * 50)
    
    try:
        # Step 1: Use Ollama with tool calling to generate four distinct search queries
        response = requests.post(
            OLLAMA_API_URL,
            headers=API_HEADERS,
            json={
                "model": AI_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a research assistant. Use the search_engine tool to generate four distinct search queries that will help gather a broad range of information related to the user's query. Each query should focus on a different aspect or angle of the topic."},
                    *context,
                    {"role": "user", "content": query},
                ],
                "tools": [
                    {
                        'type': 'function',
                        'function': {
                            'name': 'search_engine',
                            'description': 'A Wikipedia search engine. Generate four distinct search queries to maximize the spread of search results.',
                            'parameters': {
                                'type': 'object',
                                'properties': {
                                    'queries': {
                                        'type': 'array',
                                        'items': {
                                            'type': 'string',
                                            'description': 'A distinct search query focusing on a specific aspect of the topic.'
                                        },
                                        'minItems': 4,
                                        'maxItems': 4,
                                        'description': 'Four distinct search queries to maximize the spread of search results.'
                                    },
                                },
                                'required': ['queries']
                            },
                        },
                    },
                ],
                "stream": False,
                "options": {
                    "temperature": 0.48,
                    "num_ctx": 32768,
                }
            }
        )
        response.raise_for_status()
        debug_print("Response", response.json())
        tool_calls = response.json().get("message", {}).get("tool_calls", [])
        if tool_calls:
            debug_print("Tool calls", tool_calls)
            tool_call = tool_calls[0]
            if tool_call["function"]["name"] == "search_engine":
                # Access the arguments directly (it's already a dictionary)
                arguments = tool_call["function"]["arguments"]
                search_queries = arguments.get("queries", [])
                debug_print("Generated search queries", search_queries)
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
                
                # Step 4: Fetch content for all 3 articles
                articles_data, combined_content, citations = fetch_multiple_articles(top_3_headings)
                if not articles_data:
                    return "Failed to fetch article content. This can happen if the ZIM file path is incorrect or if the AI made a mistake in selecting the headings."
                debug_print("Articles data", articles_data)
                debug_print("Combined content", combined_content, max_length=500)
                debug_print("Citations", citations)
                updated_context = context + [
                    {"role": "user", "content": query},
                    {"role": "assistant", "content": f"Search results from {len(articles_data)} articles: {combined_content}"}
                ]
                debug_print("Updated context", updated_context)
                # Step 5: Generate a detailed response based on the aggregated search results
                # Combine all citations
                all_citations = "\n".join(citations)
                print(f"🔗 Using {len(articles_data)} article URLs")
                debug_print("All citations", all_citations)
                
                def generate_final_response():
                    # First, yield all citations
                    yield all_citations + "\n\n"
                    
                    final_response = requests.post(
                        OLLAMA_API_URL,
                        json={
                            "model": AI_MODEL,
                            "messages": [
                                {"role": "system", "content": f'''You are an expert research assistant. You have been provided with content from multiple Wikipedia articles. Your task is to synthesize information from all these sources to provide a comprehensive, detailed response to the user's query.

Instructions:
1. Analyze and synthesize information from ALL provided articles
2. Identify connections, patterns, and relationships between the different sources
3. Present a unified, comprehensive analysis that draws from multiple perspectives
4. Highlight areas where sources agree, disagree, or complement each other
5. Unless other wise asked, provide only moderate detail and implications
6. Ensure your response is well-structured and flows logically

Additional Instructions: Enclose LaTeX math equations (if any) in $$. Example: $x^2 + y^2 = z^2$ and $( E = mc^2 $)'''},
                                *updated_context,
                                {"role": "user", "content": f"The users query is: {query}"},
                                {"role": "user", "content": f"The search results from {len(articles_data)} articles are: {combined_content}"}
                            ],
                            "stream": True,
                            "options": {
                                "temperature": 0.48,
                                "num_ctx": 32768,
                            }
                        },
                        stream=True
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
                return Response(stream_with_context(generate_final_response()), content_type='text/plain')
        # If no tool calls, return the response as a string
        return response.json()["message"]["content"]
    except Exception as e:
        print(f"Error: {e}")
        return "An error occurred! This is most likely due to a connection issue with Ollama. Ensure that Ollama is running and that the model (default qwen2.5:3b) is available.", 500
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
        app.run(port=PORT, debug=True)
    finally:
        # Ensure kiwix-serve is stopped when the app exits
        stop_kiwix_serve()