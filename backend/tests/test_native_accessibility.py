from agent.computer_use.native_windows import accessibility


class FakeNode:
    def __init__(self, name, control_type="Button", bounds=(1, 2, 11, 12), children=None):
        self.name = name
        self.control_type = control_type
        self.bounds = bounds
        self.children = children or []


def test_normalize_tree_assigns_stable_indexes():
    root = FakeNode("Root", "Window", children=[FakeNode("OK"), FakeNode("Cancel")])

    state = accessibility.normalize_fake_tree(root)

    assert state["tree"].splitlines()[0].startswith("[0] Window")
    assert "[1] Button name='OK'" in state["tree"]
    assert state["elements"][2]["name"] == "Cancel"
    assert state["elements"][1]["bounds"] == {"x": 1, "y": 2, "width": 10, "height": 10}


def test_element_center_uses_index_bounds():
    state = {"elements": [{"index": 0, "bounds": {"x": 10, "y": 20, "width": 30, "height": 40}}]}

    assert accessibility.element_center(state, 0) == (25, 40)
