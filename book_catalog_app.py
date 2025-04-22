import os
import requests
import json
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
load_dotenv()

# Define the BookTracker class directly in this file to avoid dependency issues
class BookTracker:
    def __init__(self, notion_token, database_id):
        self.notion_token = notion_token
        self.database_id = database_id
        self.headers = {
            "Authorization": f"Bearer {notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }

    def search_by_isbn(self, isbn):
        """Check if book already exists in Notion database"""
        url = f"https://api.notion.com/v1/databases/{self.database_id}/query"
        payload = {
            "filter": {
                "property": "ISBN",
                "rich_text": {
                    "equals": isbn
                }
            }
        }
        response = requests.post(url, headers=self.headers, json=payload)
        response.raise_for_status()
        results = response.json().get("results", [])
        return results

    def fetch_open_library_data(self, isbn):
        """Fetch book data from Open Library API"""
        print(f"Fetching data for ISBN: {isbn} from Open Library...")
        url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            return data.get(f"ISBN:{isbn}", None)
        else:
            print(f"Error fetching from Open Library: {response.status_code}")
            return None

    def fetch_google_books_data(self, isbn):
        """Fetch book data from Google Books API"""
        print(f"Fetching data for ISBN: {isbn} from Google Books...")
        url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if "items" in data and len(data["items"]) > 0:
                return data["items"][0]["volumeInfo"]
        else:
            print(f"Error fetching from Google Books: {response.status_code}")
        return None

    def format_notion_properties(self, isbn, ol_data, google_data):
        """Format book data for Notion properties"""
        properties = {
            "ISBN": {"rich_text": [{"text": {"content": isbn}}]},
            "Status": {"select": {"name": "To Read"}}
        }

        # Title
        if ol_data and "title" in ol_data:
            properties["Title"] = {"title": [{"text": {"content": ol_data["title"]}}]}
        elif google_data and "title" in google_data:
            properties["Title"] = {"title": [{"text": {"content": google_data["title"]}}]}
        else:
            properties["Title"] = {"title": [{"text": {"content": "Unknown Title"}}]}

        # Authors
        authors = []
        if ol_data and "authors" in ol_data:
            authors = [author.get("name", "") for author in ol_data["authors"]]
        elif google_data and "authors" in google_data:
            authors = google_data["authors"]
        if authors:
            properties["Author"] = {"multi_select": [{"name": author} for author in authors]}

        # Publication Year
        pub_year = None
        if ol_data and "publish_date" in ol_data:
            for word in ol_data["publish_date"].split():
                if word.isdigit() and len(word) == 4:
                    pub_year = int(word)
                    break
        elif google_data and "publishedDate" in google_data:
            pub_year = int(google_data["publishedDate"].split("-")[0])
        if pub_year:
            properties["Publication Year"] = {"number": pub_year}

        # Page Count
        if ol_data and "number_of_pages" in ol_data:
            properties["Pages"] = {"number": ol_data["number_of_pages"]}
        elif google_data and "pageCount" in google_data:
            properties["Pages"] = {"number": google_data["pageCount"]}

        # Genres/Categories
        categories = []
        if ol_data and "subjects" in ol_data:
            categories = [subject["name"] for subject in ol_data["subjects"][:5]]
        elif google_data and "categories" in google_data:
            categories = google_data["categories"][:5]
        if categories:
            properties["Genre"] = {"multi_select": [{"name": category} for category in categories]}

        # Publisher
        if ol_data and "publishers" in ol_data and len(ol_data["publishers"]) > 0:
            publisher = ol_data["publishers"][0].get("name", "")
            properties["Publisher"] = {"rich_text": [{"text": {"content": publisher}}]}
        elif google_data and "publisher" in google_data:
            properties["Publisher"] = {"rich_text": [{"text": {"content": google_data["publisher"]}}]}

        return properties

    def create_book_page(self, isbn, properties, ol_data=None, google_data=None):
        """Create a new page in Notion with book data"""
        description = ""
        if google_data and "description" in google_data:
            description = google_data["description"]
        elif ol_data and "excerpts" in ol_data and len(ol_data["excerpts"]) > 0:
            description = ol_data["excerpts"][0].get("text", "")

        page_content = [
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "Description"}}]
                }
            }
        ]
        if description:
            page_content.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": description}}]
                }
            })
        page_content.extend([
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "Reading Notes"}}]
                }
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": ""}}]
                }
            }
        ])

        url = "https://api.notion.com/v1/pages"
        payload = {
            "parent": {"database_id": self.database_id},
            "properties": properties,
            "children": page_content
        }
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error creating Notion page: {e}")
            print(f"Response status code: {response.status_code if 'response' in locals() else 'N/A'}")
            print(f"Response text: {response.text if 'response' in locals() else 'N/A'}")
            return None

# Flask app setup
app = Flask(__name__)

# Configuration
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "NOTION_TOKEN")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "NOTION_DATABASE_ID")
book_tracker = BookTracker(NOTION_TOKEN, NOTION_DATABASE_ID)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/add_book', methods=['POST'])
def add_book():
    data = request.get_json()
    book = data.get('book', {})
    isbn = book.get('isbn', '')

    if not book.get('title') or not book.get('authors'):
        return jsonify({'success': False, 'message': 'Title and author(s) are required'})

    if isbn:
        try:
            existing = book_tracker.search_by_isbn(isbn)
            if existing:
                return jsonify({'success': False, 'message': f'Book with ISBN {isbn} already exists'})
        except Exception as e:
            print(f"Error checking if book exists: {e}")

    properties = {
        "Title": {"title": [{"text": {"content": book.get('title', 'Unknown Title')}}]},
        "Status": {"select": {"name": "To Read"}}
    }
    if isbn:
        properties["ISBN"] = {"rich_text": [{"text": {"content": isbn}}]}
    if book.get('authors'):
        properties["Author"] = {"multi_select": [{"name": author} for author in book.get('authors')]}
    if book.get('publishedDate'):
        try:
            pub_year = int(book.get('publishedDate'))
            properties["Publication Year"] = {"number": pub_year}
        except:
            pass
    if book.get('pageCount'):
        properties["Pages"] = {"number": book.get('pageCount')}
    if book.get('categories'):
        genres = []
        if isinstance(book.get('categories'), list):
            if len(book.get('categories')) == 1 and isinstance(book.get('categories')[0], str):
                genres = [category.strip().title() for category in book.get('categories')[0].split(',')]
            else:
                genres = [category.strip().title() for category in book.get('categories')]
        elif isinstance(book.get('categories'), str):
            genres = [category.strip().title() for category in book.get('categories').split(',')]
        properties["Genre"] = {"multi_select": [{"name": genre} for genre in genres]}
    if book.get('publisher'):
        properties["Publisher"] = {"rich_text": [{"text": {"content": book.get('publisher')}}]}
    if isbn:
        cover_url = f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg"
        properties["Cover"] = {
            "files": [
                {
                    "type": "external",
                    "name": "Cover Image",
                    "external": {"url": cover_url}
                }
            ]
        }

    page_content = [
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Description"}}]
            }
        }
    ]
    if book.get('description'):
        page_content.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": book.get('description')}}]
            }
        })
    page_content.extend([
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Reading Notes"}}]
            }
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": ""}}]
            }
        }
    ])

    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties,
        "children": page_content
    }
    try:
        response = requests.post(url, headers=book_tracker.headers, json=payload)
        response.raise_for_status()
        return jsonify({'success': True, 'message': 'Book added successfully'})
    except Exception as e:
        print(f"Error creating Notion page: {e}")
        print(f"Response status code: {response.status_code if 'response' in locals() else 'N/A'}")
        print(f"Response text: {response.text if 'response' in locals() else 'N/A'}")
        return jsonify({'success': False, 'message': f'Failed to add book: {str(e)}'})

@app.route('/search_books', methods=['POST'])
def search_books():
    data = request.get_json()
    query = data.get('query', '')
    search_type = data.get('search_type', 'general')

    if not query:
        return jsonify({'success': False, 'message': 'Search query is required', 'results': []})

    clean_query = query.replace('-', '').replace(' ', '')
    is_likely_isbn = clean_query.isdigit() and (len(clean_query) == 10 or len(clean_query) == 13)

    results = []
    if is_likely_isbn:
        print(f"Query appears to be an ISBN: {clean_query}")
        ol_url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{clean_query}&format=json&jscmd=data"
        ol_response = requests.get(ol_url)
        if ol_response.status_code == 200:
            ol_data = ol_response.json()
            if f"ISBN:{clean_query}" in ol_data:
                book_data = ol_data[f"ISBN:{clean_query}"]
                ol_book = {
                    'title': book_data.get('title', 'Unknown Title'),
                    'authors': [author.get('name', 'Unknown Author') for author in book_data.get('authors', [])],
                    'publishedDate': book_data.get('publish_date', ''),
                    'description': book_data.get('notes', ''),
                    'pageCount': book_data.get('number_of_pages', 0),
                    'categories': [subject.get('name', '') for subject in book_data.get('subjects', [])[:5]] if 'subjects' in book_data else [],
                    'isbn': clean_query,
                    'thumbnail': f"https://covers.openlibrary.org/b/isbn/{clean_query}-M.jpg",
                    'exactMatch': True
                }
                results.append(ol_book)
                if search_type == 'exact_isbn':
                    return jsonify({'success': True, 'message': 'Exact ISBN match found in Open Library', 'results': results})

    google_results = fetch_google_books_results(query)
    isbns = [book['isbn'] for book in google_results if book.get('isbn')]
    ol_covers = fetch_open_library_covers(isbns)
    for book in google_results:
        if book.get('isbn') and f"ISBN:{book['isbn']}" in ol_covers:
            book['thumbnail'] = f"https://covers.openlibrary.org/b/isbn/{book['isbn']}-M.jpg"
        results.append(book)

    # Check if results are empty and return a custom message
    if not results:
        return jsonify({'success': False, 'message': 'No books found for the given query.', 'results': []})
    return jsonify({'success': True, 'message': 'Books found', 'results': results})

def fetch_open_library_covers(isbns):
    """Fetch cover URLs for multiple ISBNs from Open Library."""
    if not isbns:
        return {}
    query = ",".join([f"ISBN:{isbn}" for isbn in isbns])
    url = f"https://openlibrary.org/api/books?bibkeys={query}&format=json&jscmd=data"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching Open Library covers: {response.status_code}")
        return {}

def fetch_google_books_results(query):
    """Fetch general search results from Google Books API."""
    url = f"https://www.googleapis.com/books/v1/volumes?q={query}&maxResults=20"
    response = requests.get(url)
    results = []
    if response.status_code == 200:
        data = response.json()
        if "items" in data:
            for item in data["items"]:
                volume_info = item.get("volumeInfo", {})
                isbn_13 = None
                isbn_10 = None
                identifiers = volume_info.get("industryIdentifiers", [])
                for id_obj in identifiers:
                    if id_obj.get("type") == "ISBN_13":
                        isbn_13 = id_obj.get("identifier")
                    elif id_obj.get("type") == "ISBN_10":
                        isbn_10 = id_obj.get("identifier")
                thumbnail = volume_info.get("imageLinks", {}).get("thumbnail", "/static/book-placeholder.png")
                results.append({
                    "title": volume_info.get("title", "Unknown Title"),
                    "authors": volume_info.get("authors", ["Unknown Author"]),
                    "publishedDate": volume_info.get("publishedDate", ""),
                    "description": volume_info.get("description", ""),
                    "pageCount": volume_info.get("pageCount", 0),
                    "categories": volume_info.get("categories", []),
                    "isbn": isbn_13 or isbn_10,
                    "thumbnail": thumbnail
                })
    return results

if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)