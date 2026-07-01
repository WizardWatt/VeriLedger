"""
VeriLedger — Forgery Network Graph
======================================
Builds a graph where:
  - Nodes  = documents
  - Edges  = shared entities (survey numbers, signatories, registration offices, etc.)

High-suspicion subgraphs surface fraud rings (same survey number reused across
unrelated applicants) and document recycling (same signatory on many docs).
"""

from __future__ import annotations
import networkx as nx
from collections import defaultdict
from typing import Optional
import plotly.graph_objects as go
import json

from models.entities import ExtractedDocument, GraphEdge, SharedEntityFields, RiskLevel

# Fields that, if shared between two documents, create a graph edge.
# Weight = how suspicious that shared field is.
LINKAGE_FIELDS: dict[str, float] = {
    # ── Original fields ───────────────────────────────────────────────────────
    "survey_number":       0.9,   # Very suspicious if two unrelated applicants share this
    "signatory_name":      0.6,
    "registration_office": 0.3,   # Low weight — same office is normal
    "applicant_id":        0.95,  # Near-certain fraud signal if same ID on different docs
    "pan_number":          0.85,  # Links ITR ↔ payslip ↔ GST ↔ bank statement
    "notary_id":           0.5,
    "bank_account_number": 0.8,   # Links payslip ↔ bank statement
    "advocate_name":       0.4,
    "property_address":    0.75,
    "company_name":        0.55,  # Links GST return ↔ financial statement
    # ── New fields for expanded doc types ────────────────────────────────────
    "gstin":               0.9,   # GST return: same GSTIN on different applicants = identity theft
    "employer_name":       0.65,  # Payslip ↔ ITR: same employer is normal; cross-applicant = fabrication
    "acknowledgement_no":  0.95,  # ITR ack number must be unique — reuse = cloned ITR
    # ── Round 2: panel-required doc types ────────────────────────────────────
    "ca_membership_number":  0.8,  # Same CA certifying net worth for multiple unrelated applicants
    "municipal_property_id": 0.85, # Same ward/property ID on tax receipts across applicants
    "plan_approval_number":  0.9,  # OC referencing a plan approval number seen on another doc
    "udyam_number":          0.9,  # Same Udyam number reused across different applicants
    "aadhaar_number":        0.95, # Same Aadhaar across different applicant_ids = identity theft
}


class ForgeryGraph:
    def __init__(self):
        self.G = nx.Graph()
        # entity_index[field][value] = list of document_ids
        self.entity_index: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        self._docs: dict[str, ExtractedDocument] = {}

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def add_document(self, doc: ExtractedDocument) -> None:
        """Add a document to the graph and create edges to all previously matching docs."""
        self._docs[doc.document_id] = doc
        shared = doc.shared_fields()

        # Add node
        self.G.add_node(
            doc.document_id,
            doc_type=doc.doc_type.value,
            risk_score=doc.risk_score,
            risk_level=doc.risk_level.value,
            applicant_id=shared.applicant_id or "",
            label=doc.document_id,
        )

        # For each linkage field, check if any existing doc shares the same value
        for field, weight in LINKAGE_FIELDS.items():
            value = getattr(shared, field, None)
            if not value:
                continue

            norm_value = str(value).strip().lower()
            existing_docs = self.entity_index[field][norm_value]

            # Deduplicate while preserving insertion order.
            # Guards against a doc_id being indexed multiple times if
            # add_document() is called more than once for the same document.
            unique_existing = list(dict.fromkeys(existing_docs))

            for existing_doc_id in unique_existing:
                if existing_doc_id == doc.document_id:
                    continue

                edge_key = tuple(sorted([doc.document_id, existing_doc_id]))

                if self.G.has_edge(*edge_key):
                    # Strengthen existing edge
                    self.G[edge_key[0]][edge_key[1]]["weight"] = min(
                        1.0, self.G[edge_key[0]][edge_key[1]]["weight"] + weight * 0.3
                    )
                    existing = self.G[edge_key[0]][edge_key[1]]["shared_fields"]
                    if field not in existing:
                        existing.append(field)
                else:
                    self.G.add_edge(
                        *edge_key,
                        weight=weight,
                        shared_fields=[field],
                        shared_value=value,
                        primary_field=field,
                    )

            # Index this doc's value
            existing_docs.append(doc.document_id)

    def add_documents(self, docs: list[ExtractedDocument]) -> None:
        for doc in docs:
            self.add_document(doc)

    # ── Analysis ──────────────────────────────────────────────────────────────

    def get_flags_for_document(self, document_id: str) -> list[str]:
        """Return human-readable suspicion flags for a single document."""
        flags = []
        if document_id not in self.G:
            return flags

        neighbors = list(self.G.neighbors(document_id))
        if not neighbors:
            return flags

        for neighbor in neighbors:
            edge = self.G[document_id][neighbor]
            weight = edge.get("weight", 0)
            shared = ", ".join(dict.fromkeys(edge.get("shared_fields", [])))
            flags.append(
                f"Shares [{shared}] with {neighbor} (suspicion: {weight:.2f})"
            )

        # Flag high-degree nodes (hub in fraud ring)
        degree = self.G.degree(document_id)
        if degree >= 3:
            flags.append(f"High connectivity — linked to {degree} other documents (possible fraud hub)")

        return flags

    def get_suspicious_clusters(self, min_weight: float = 0.6) -> list[list[str]]:
        """Return clusters of highly suspicious documents."""
        subgraph = nx.Graph([
            (u, v) for u, v, d in self.G.edges(data=True)
            if d.get("weight", 0) >= min_weight
        ])
        return [list(c) for c in nx.connected_components(subgraph) if len(c) > 1]

    def get_risk_scores(self) -> dict[str, float]:
        """
        Compute a graph-based risk score per document.
        PageRank-ish: nodes with many high-weight edges to other suspicious nodes score higher.
        """
        if len(self.G.nodes) == 0:
            return {}

        # Use weighted degree centrality as a simple proxy
        scores = {}
        for node in self.G.nodes:
            weighted_degree = sum(
                d.get("weight", 0) for _, _, d in self.G.edges(node, data=True)
            )
            # Normalize to 0–1 roughly
            scores[node] = min(1.0, weighted_degree / max(1, len(self.G.nodes) * 0.5))
        return scores

    def graph_summary(self) -> dict:
        clusters = self.get_suspicious_clusters()
        return {
            "total_documents": self.G.number_of_nodes(),
            "total_links": self.G.number_of_edges(),
            "suspicious_clusters": len(clusters),
            "largest_cluster_size": max((len(c) for c in clusters), default=0),
            "cluster_members": clusters,
        }

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_json(self) -> dict:
        """Serialize graph to node-link format for API responses.
        NetworkX 3.x uses 'edges' key; normalize to 'links' for D3/Plotly consumers.
        """
        data = nx.node_link_data(self.G)
        raw = json.loads(json.dumps(data, default=str))
        if 'edges' in raw and 'links' not in raw:
            raw['links'] = raw.pop('edges')
        return raw

    # ── Plotly Visualization ───────────────────────────────────────────────────

    def to_plotly_figure(self) -> go.Figure:
        """Return a Plotly figure of the forgery network."""
        if len(self.G.nodes) == 0:
            return go.Figure()

        pos = nx.spring_layout(self.G, seed=42)

        # Edges
        edge_x, edge_y, edge_weights = [], [], []
        for u, v, data in self.G.edges(data=True):
            x0, y0 = pos[u]
            x1, y1 = pos[v]
            edge_x += [x0, x1, None]
            edge_y += [y0, y1, None]
            edge_weights.append(data.get("weight", 0.5))

        edge_trace = go.Scatter(
            x=edge_x, y=edge_y, mode="lines",
            line=dict(width=1.5, color="#ff4444"),
            hoverinfo="none",
        )

        # Nodes
        node_x = [pos[n][0] for n in self.G.nodes]
        node_y = [pos[n][1] for n in self.G.nodes]
        risk_scores = self.get_risk_scores()
        node_colors = [risk_scores.get(n, 0) for n in self.G.nodes]
        node_text = [
            f"{n}<br>Type: {self.G.nodes[n].get('doc_type','?')}<br>"
            f"Risk: {risk_scores.get(n, 0):.2f}"
            for n in self.G.nodes
        ]

        node_trace = go.Scatter(
            x=node_x, y=node_y, mode="markers+text",
            text=list(self.G.nodes),
            textposition="top center",
            hovertext=node_text,
            hoverinfo="text",
            marker=dict(
                size=18,
                color=node_colors,
                colorscale="RdYlGn_r",
                cmin=0, cmax=1,
                colorbar=dict(title="Risk Score"),
                line=dict(width=2, color="white"),
            ),
        )

        fig = go.Figure(
            data=[edge_trace, node_trace],
            layout=go.Layout(
                title="VeriLedger — Forgery Network Graph",
                showlegend=False,
                hovermode="closest",
                xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                paper_bgcolor="#0f1117",
                plot_bgcolor="#0f1117",
                font=dict(color="white"),
                margin=dict(t=50, b=20, l=20, r=20),
            ),
        )
        return fig