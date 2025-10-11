#!/usr/bin/env python3
"""
Test script to demonstrate the file saving functionality in verbose debug mode.
"""

import re
import os
import time
from bs4 import BeautifulSoup

def convert_html_to_markdown(html_content, verbose_debug=False):
    """
    Convert HTML content to clean markdown format.
    Handles headings, tables, lists, and links while removing unnecessary HTML markup.
    
    Args:
        html_content (str): The HTML content to convert
        verbose_debug (bool): Whether to print debug information
    
    Returns:
        str: Clean markdown content
    """
    if not html_content:
        return ""
    
    # Parse HTML
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove script, style, and other non-content elements
    for element in soup.find_all(['script', 'style', 'nav', 'footer', 'header']):
        element.decompose()
    
    # Convert headings (h1-h6) to markdown
    for i in range(1, 7):
        for heading in soup.find_all(f'h{i}'):
            # Get the text content
            heading_text = heading.get_text().strip()
            if heading_text:
                # Create markdown heading with appropriate number of #
                markdown_heading = f"{'#' * i} {heading_text}"
                # Replace the heading with markdown
                heading.replace_with(markdown_heading)
    
    # Convert tables to markdown tables
    for table in soup.find_all('table'):
        markdown_table = convert_table_to_markdown(table)
        if markdown_table:
            table.replace_with(markdown_table)
    
    # Convert lists to markdown lists
    for ul in soup.find_all('ul'):
        markdown_list = convert_list_to_markdown(ul, ordered=False)
        if markdown_list:
            ul.replace_with(markdown_list)
    
    for ol in soup.find_all('ol'):
        markdown_list = convert_list_to_markdown(ol, ordered=True)
        if markdown_list:
            ol.replace_with(markdown_list)
    
    # Convert links to markdown links
    for link in soup.find_all('a'):
        href = link.get('href', '')
        text = link.get_text().strip()
        if href and text:
            markdown_link = f"[{text}]({href})"
            link.replace_with(markdown_link)
    
    # Convert paragraphs and other block elements
    for p in soup.find_all('p'):
        p_text = p.get_text().strip()
        if p_text:
            p.replace_with(p_text + '\n\n')
    
    # Convert divs to line breaks
    for div in soup.find_all('div'):
        div_text = div.get_text().strip()
        if div_text:
            div.replace_with(div_text + '\n')
    
    # Get the final text content
    markdown_content = soup.get_text()
    
    # Clean up excessive whitespace
    markdown_content = re.sub(r'\n\s*\n\s*\n', '\n\n', markdown_content)
    markdown_content = re.sub(r'[ \t]+', ' ', markdown_content)
    markdown_content = markdown_content.strip()
    
    if verbose_debug:
        print(f"\n=== HTML TO MARKDOWN CONVERSION ===")
        print(f"Original HTML length: {len(html_content)} characters")
        print(f"Markdown length: {len(markdown_content)} characters")
        print(f"Reduction: {((len(html_content) - len(markdown_content)) / len(html_content) * 100):.1f}%")
        
        # Save before and after files for comparison
        timestamp = int(time.time())
        
        # Save original HTML content
        html_filename = f"html_before_conversion_{timestamp}.html"
        with open(html_filename, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"Original HTML saved to: {html_filename}")
        
        # Save converted markdown content
        markdown_filename = f"markdown_after_conversion_{timestamp}.md"
        with open(markdown_filename, 'w', encoding='utf-8') as f:
            f.write(markdown_content)
        print(f"Converted Markdown saved to: {markdown_filename}")
        
        print("=" * 50)
    
    return markdown_content

def convert_table_to_markdown(table):
    """Convert an HTML table to markdown table format."""
    try:
        rows = []
        
        # Get all table rows
        for tr in table.find_all('tr'):
            row = []
            for cell in tr.find_all(['td', 'th']):
                cell_text = cell.get_text().strip()
                # Clean up cell text
                cell_text = re.sub(r'\s+', ' ', cell_text)
                row.append(cell_text)
            
            if row:  # Only add non-empty rows
                rows.append(row)
        
        if not rows:
            return ""
        
        # Create markdown table
        markdown_lines = []
        
        # Add header row
        if rows:
            header = rows[0]
            markdown_lines.append('| ' + ' | '.join(header) + ' |')
            markdown_lines.append('| ' + ' | '.join(['---'] * len(header)) + ' |')
            
            # Add data rows
            for row in rows[1:]:
                # Ensure row has same number of columns as header
                while len(row) < len(header):
                    row.append('')
                markdown_lines.append('| ' + ' | '.join(row) + ' |')
        
        return '\n'.join(markdown_lines) + '\n\n'
    
    except Exception as e:
        print(f"Error converting table to markdown: {e}")
        return ""

def convert_list_to_markdown(list_element, ordered=False):
    """Convert an HTML list to markdown list format."""
    try:
        markdown_lines = []
        
        for i, li in enumerate(list_element.find_all('li'), 1):
            li_text = li.get_text().strip()
            if li_text:
                if ordered:
                    markdown_lines.append(f"{i}. {li_text}")
                else:
                    markdown_lines.append(f"- {li_text}")
        
        return '\n'.join(markdown_lines) + '\n\n' if markdown_lines else ""
    
    except Exception as e:
        print(f"Error converting list to markdown: {e}")
        return ""

def test_file_saving():
    """Test the file saving functionality."""
    
    print("Testing file saving functionality...")
    print("=" * 60)
    
    # Create a comprehensive test HTML
    test_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>COPD Information</title>
        <style>body { font-family: Arial; }</style>
    </head>
    <body>
        <div class="article">
            <h1>Chronic Obstructive Pulmonary Disease</h1>
            <p>COPD is a chronic inflammatory lung disease that obstructs airflow from the lungs.</p>
            
            <h2>Symptoms</h2>
            <table class="infobox">
                <tr>
                    <th>Symptom</th>
                    <th>Description</th>
                </tr>
                <tr>
                    <td>Shortness of breath</td>
                    <td>Difficulty breathing, especially during activity</td>
                </tr>
                <tr>
                    <td>Chronic cough</td>
                    <td>Persistent cough with mucus production</td>
                </tr>
            </table>
            
            <h3>Common Causes</h3>
            <ul>
                <li>Tobacco smoking</li>
                <li>Air pollution</li>
                <li>Occupational exposure to dust and chemicals</li>
            </ul>
            
            <h3>Treatment Steps</h3>
            <ol>
                <li>Stop smoking immediately</li>
                <li>Pulmonary rehabilitation</li>
                <li>Medication management</li>
                <li>Oxygen therapy if needed</li>
            </ol>
            
            <p>For more information, visit <a href="https://example.com/copd">our COPD resource page</a>.</p>
        </div>
    </body>
    </html>
    """
    
    print("\nConverting HTML to Markdown with file saving...")
    print("-" * 50)
    
    # Convert with verbose debugging enabled
    markdown_result = convert_html_to_markdown(test_html, verbose_debug=True)
    
    print(f"\nConversion completed!")
    print(f"Final markdown length: {len(markdown_result)} characters")
    
    # List the files that were created
    print(f"\nFiles created in current directory:")
    current_files = [f for f in os.listdir('.') if f.startswith(('html_before_conversion_', 'markdown_after_conversion_'))]
    for file in sorted(current_files):
        file_size = os.path.getsize(file)
        print(f"  - {file} ({file_size} bytes)")

if __name__ == "__main__":
    test_file_saving()
