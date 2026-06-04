from agent.computer_use.routing_policy import classify_computer_use_request


def test_youtube_search_routes_to_browser_with_direct_results_url():
    route = classify_computer_use_request("open brave, go to youtube, search for ksi, click the first video")

    assert route["mode"] == "browser"
    assert route["intent"] == "web_task"
    assert route["status"] == "available"
    assert route["recommended_actions"][0] == {
        "tool": "browser_navigate",
        "url": "https://www.youtube.com/results?search_query=ksi",
    }
    assert route["fallback_mode"] == "desktop"


def test_generic_website_task_routes_to_browser():
    route = classify_computer_use_request("open swiggy and find a non veg meal")

    assert route["mode"] == "browser"
    assert route["intent"] == "web_task"
    assert route["recommended_actions"][0] == {
        "tool": "browser_navigate",
        "url": "https://www.swiggy.com",
    }


def test_installed_app_task_routes_to_native_desktop():
    route = classify_computer_use_request("open notepad and type hello")

    assert route["mode"] == "desktop"
    assert route["intent"] == "installed_app"
    assert route["required_permission"] == "open_apps"
    assert route["recommended_actions"][0] == {
        "tool": "computer_use",
        "mode": "desktop",
        "action": "open_app",
        "app": "notepad",
    }


def test_terminal_task_routes_to_workspace():
    route = classify_computer_use_request("run pytest backend/tests/test_api.py in the terminal")

    assert route["mode"] == "workspace"
    assert route["intent"] == "terminal"
    assert route["recommended_actions"][0] == {
        "tool": "computer_use",
        "mode": "workspace",
        "action": "terminal.run",
    }


def test_cua_and_cloud_vm_requests_are_marked_coming_soon():
    route = classify_computer_use_request("use the CUA driver in a cloud VM so I can use the laptop too")

    assert route["mode"] == "coming_soon"
    assert route["intent"] == "cloud_vm_or_cua"
    assert route["status"] == "coming_soon"
    assert route["recommended_actions"] == []
