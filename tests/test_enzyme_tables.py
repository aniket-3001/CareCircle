"""The FDA page's laboratory (in vitro) and transporter tables: parsed, loaded as the weakest kind of flag, and never allowed to replace a clinical path."""
import pathlib

from carecircle import reference
from carecircle.checks import Checker

SNAP = pathlib.Path(__file__).resolve().parents[1] / "carecircle" / "snapshot" / "fda_cyp.html"


def parsed():
    return reference.parse_fda_cyp(SNAP.read_text(encoding="utf-8", errors="ignore"))


def test_the_in_vitro_and_transporter_tables_are_read_with_the_names_the_graph_uses():
    f = parsed()
    assert ("ketoconazole", "CYP3A", "in vitro") in f["vitro_inhibits"]                   # 'CYP3A4/5' on the page, 'CYP3A' in the graph
    assert ("digoxin", "P-gp") in f["transporter_substrates"] and ("quinidine", "P-gp") in f["transporter_inhibits"]
    assert ("metformin", "OCT2") in f["transporter_substrates"] and ("cimetidine", "OCT2") in f["transporter_inhibits"]
    assert len(f["transporter_substrates"]) > 30 and len(f["vitro_inhibits"]) > 15
    assert len(f["inhibits"]) == 13 and len(f["substrates"]) == 12                         # the clinical tables are unchanged


def test_a_transporter_path_is_a_labelled_laboratory_finding_with_the_lowest_weight():
    c = Checker().check(["digoxin", "quinidine"])
    p = [x for x in c["enzyme_paths"] if x["target"] == "transporter"]
    assert len(p) == 1 and p[0]["strength"] == "in vitro" and p[0]["weight"] == 0.1
    assert "P-gp transporter" in p[0]["meaning"] and "laboratory finding, not shown in people" in p[0]["meaning"]
    assert "transporter in vitro table" in p[0]["source"]


def test_several_shared_transporters_make_one_flag_not_three():
    c = Checker().check(["cimetidine", "metformin"])
    p = [x for x in c["enzyme_paths"] if x["x"] == "cimetidine" and x["y"] == "metformin"]
    assert len(p) == 1 and "(also" in p[0]["meaning"]
    assert all(name in p[0]["meaning"] for name in ("MATE1", "MATE-2K", "OCT2"))


def test_a_clinical_path_is_never_replaced_by_a_laboratory_one_for_the_same_pair():
    c = Checker().check(["clarithromycin", "atorvastatin", "ketoconazole"])
    by = {(x["x"], x["y"]): x for x in c["enzyme_paths"]}
    assert by[("clarithromycin", "atorvastatin")]["strength"] == "strong" and "index table" in by[("clarithromycin", "atorvastatin")]["source"]
    assert by[("ketoconazole", "atorvastatin")]["strength"] == "in vitro"                    # the FDA clinical table does not list ketoconazole here: only the laboratory finding exists, and it says so


def test_the_reference_graph_records_its_version_so_start_up_reloads_an_older_shape():
    from falkordb import FalkorDB
    g = FalkorDB().select_graph(reference.REF_GRAPH)
    got = g.ro_query("MATCH (m:Meta {key:'ref'}) RETURN m.version").result_set
    assert got and got[0][0] == reference.REF_VERSION


def test_no_table_yields_a_fragment_of_a_footnote_and_cyclosporine_keeps_all_its_transporters():
    """N8: '(a,b,d,,h,i)' (a double comma) was not recognised as a footnote marker, so the parser emitted 'b', 'd', 'h', 'i)' and 'cyclosporine (a' as medicines."""
    from pathlib import Path
    from carecircle import reference as R
    f = R.parse_fda_cyp((Path(R.__file__).parent / "snapshot" / "fda_cyp.html").read_text(encoding="utf-8", errors="ignore"))
    names = {x[0] for rows in f.values() for x in rows}
    assert not [n for n in names if len(n) <= 2 or "(" in n or ")" in n or n.endswith(",")], sorted(n for n in names if len(n) <= 2 or "(" in n or ")" in n)
    assert {t for d, t in f["transporter_inhibits"] if d == "cyclosporine"} == {"P-gp", "OATP1B1", "OATP1B3"}
    assert R._drugs("cyclosporine (a,b,d,,h,i) , rifampicin (a,d,e,h) , verapamil (c,f,g)") == ["cyclosporine", "rifampicin", "verapamil"]
    assert R._drugs("elacridar (GF120918) (a) , valspodar (PSC833)") == ["elacridar", "valspodar"]
