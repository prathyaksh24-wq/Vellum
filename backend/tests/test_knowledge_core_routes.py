from agent import api


def test_knowledge_core_and_books_routes_are_mounted():
    # The Books shelf and Knowledge Core views call these under /api/knowledge/core.
    assert api.app.url_path_for("book_library_list") == "/api/knowledge/core/books/library"
