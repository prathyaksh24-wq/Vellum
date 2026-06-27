from agent.computer_use.native_windows import accessibility


class FakeNode:
    def __init__(self, name, control_type="Button", bounds=(1, 2, 11, 12), children=None):
        self.name = name
        self.control_type = control_type
        self.bounds = bounds
        self.children = children or []


class FakeRect:
    def __init__(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class FakeUiaNode:
    def __init__(self, name, control_type, bounds, children=None):
        self.CurrentName = name
        self.CurrentControlType = control_type
        self.CurrentBoundingRectangle = FakeRect(*bounds)
        self.children = children or []


class FakeWalker:
    def GetFirstChildElement(self, node):
        return node.children[0] if node.children else None

    def GetNextSiblingElement(self, node):
        siblings = getattr(node, "_siblings", [])
        if not siblings:
            return None
        index = siblings.index(node)
        if index + 1 >= len(siblings):
            return None
        return siblings[index + 1]


def _attach_siblings(node):
    for child in node.children:
        child._siblings = node.children
        _attach_siblings(child)
    return node


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


def test_normalize_uia_element_walks_children_depth_first():
    root = _attach_siblings(
        FakeUiaNode(
            "Root",
            50032,
            (0, 0, 100, 80),
            children=[
                FakeUiaNode("OK", 50000, (10, 20, 30, 50)),
                FakeUiaNode(
                    "Panel",
                    50033,
                    (1, 2, 11, 22),
                    children=[FakeUiaNode("Body", 50020, (3, 4, 13, 14))],
                ),
            ],
        )
    )

    state = accessibility._normalize_uia_element(root, walker=FakeWalker())

    assert [element["index"] for element in state["elements"]] == [0, 1, 2, 3]
    assert [element["name"] for element in state["elements"]] == ["Root", "OK", "Panel", "Body"]
    assert state["elements"][1]["role"] == "Button"
    assert state["elements"][2]["bounds"] == {"x": 1, "y": 2, "width": 10, "height": 20}
    assert state["tree"].splitlines() == [
        "[0] Window name='Root' bounds=0,0,100x80",
        "  [1] Button name='OK' bounds=10,20,20x30",
        "  [2] Pane name='Panel' bounds=1,2,10x20",
        "    [3] Text name='Body' bounds=3,4,10x10",
    ]


def test_normalize_uia_element_honors_node_limit(monkeypatch):
    root = _attach_siblings(
        FakeUiaNode(
            "Root",
            50032,
            (0, 0, 10, 10),
            children=[
                FakeUiaNode("One", 50000, (0, 0, 1, 1)),
                FakeUiaNode("Two", 50000, (0, 0, 1, 1)),
            ],
        )
    )
    monkeypatch.setattr(accessibility, "MAX_NODES", 2)

    state = accessibility._normalize_uia_element(root, walker=FakeWalker())

    assert [element["name"] for element in state["elements"]] == ["Root", "One"]
