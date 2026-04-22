from src.graph import build_graph


def test_subnet_depends_on_network(sample_report, sample_network, sample_subnet):
    graph = build_graph(sample_report.resources).graph
    assert graph.number_of_nodes() == 3
    assert graph.has_edge(sample_subnet.stable_id(), sample_network.stable_id())
    edge = graph.edges[sample_subnet.stable_id(), sample_network.stable_id()]
    assert edge["kind"] == "subnet->network"


def test_graph_exports_json_and_dot(sample_report, tmp_path):
    g = build_graph(sample_report.resources)
    g.write(tmp_path)
    assert (tmp_path / "graph.json").exists()
    assert (tmp_path / "graph.dot").exists()
    assert '"kind": "subnet->network"' in (tmp_path / "graph.json").read_text()
