import sqlite3
import json
import time
import hashlib
import re
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Tuple, Set


@dataclass
class PaperRecord:
    paper_id: str                      # DOI or SHA-256 hash of title+year
    title: str
    authors: List[str]
    year: int
    venue: str
    abstract: str
    pdf_path: Optional[str] = None
    full_text_md: Optional[str] = None
    bibtex: Optional[str] = None
    citation_count: int = 0
    created_at: float = 0.0


@dataclass
class ClaimRecord:
    claim_id: str
    paper_id: str
    claim_text: str
    section: str                       # e.g., "Methodology", "Results", "Related Work"
    quote_span: str                    # Verbatim quote from the paper
    verification_status: str           # "verified", "unverified", "contradicted"
    confidence: float                  # 0.0 to 1.0
    contradicting_claim_id: Optional[str] = None
    created_at: float = 0.0


@dataclass
class ExperimentRecord:
    experiment_id: str
    paper_id: Optional[str]
    name: str
    hypothesis: str
    commit_hash: str
    seed: int
    config: Dict[str, Any]
    metrics: Dict[str, Any]
    status: str                        # "reproduced", "diverged", "failed"
    reproduction_gap: float            # Delta from original paper metric
    created_at: float = 0.0


@dataclass
class DeadEndRecord:
    dead_end_id: str
    hypothesis: str
    failed_mechanism: str
    compute_expended_hrs: float
    root_cause: str
    created_at: float = 0.0


class ResearchMemoryLayer:
    """
    Production-grade SQLite WAL Shared Memory Layer for the Researcher Room.
    - WAL Mode for zero-lock concurrent reads and writes.
    - FTS5 Virtual Tables for sub-millisecond lexical queries on papers, claims, and notes.
    - Directed Citation Graph with BFS multi-hop traversal.
    - Experiment & Dead-End registries to prevent redundant computation.
    """

    def __init__(self, db_path: Optional[Path] = None):
        default_dir = Path("workspace/research_data")
        default_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path or (default_dir / "research_vault.db")
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            # 1. Papers Table & FTS5 Index
            conn.execute("""
                CREATE TABLE IF NOT EXISTS papers (
                    paper_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    authors_json TEXT NOT NULL,
                    year INTEGER,
                    venue TEXT,
                    abstract TEXT,
                    pdf_path TEXT,
                    full_text_md TEXT,
                    bibtex TEXT,
                    citation_count INTEGER DEFAULT 0,
                    created_at REAL NOT NULL
                );
            """)
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
                    paper_id UNINDEXED,
                    title,
                    abstract,
                    full_text_md,
                    content='papers',
                    content_rowid='rowid'
                );
            """)

            # 2. Claims Table & FTS5 Index
            conn.execute("""
                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL,
                    claim_text TEXT NOT NULL,
                    section TEXT NOT NULL,
                    quote_span TEXT NOT NULL,
                    verification_status TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    contradicting_claim_id TEXT,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE
                );
            """)
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
                    claim_id UNINDEXED,
                    claim_text,
                    quote_span,
                    content='claims',
                    content_rowid='rowid'
                );
            """)

            # 3. Directed Citation Graph
            conn.execute("""
                CREATE TABLE IF NOT EXISTS citation_graph (
                    source_paper_id TEXT NOT NULL,
                    target_paper_id TEXT NOT NULL,
                    context_snippet TEXT,
                    sentiment TEXT DEFAULT 'neutral',
                    created_at REAL NOT NULL,
                    PRIMARY KEY (source_paper_id, target_paper_id)
                );
            """)

            # 4. Reproducible Experiment Ledger
            conn.execute("""
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    paper_id TEXT,
                    name TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    commit_hash TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    config_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reproduction_gap REAL DEFAULT 0.0,
                    created_at REAL NOT NULL
                );
            """)

            # 5. Dead-End & Negative Result Registry
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dead_ends (
                    dead_end_id TEXT PRIMARY KEY,
                    hypothesis TEXT NOT NULL,
                    failed_mechanism TEXT NOT NULL,
                    compute_expended_hrs REAL NOT NULL,
                    root_cause TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
            """)
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS dead_ends_fts USING fts5(
                    dead_end_id UNINDEXED,
                    hypothesis,
                    failed_mechanism,
                    root_cause,
                    content='dead_ends',
                    content_rowid='rowid'
                );
            """)

            # 6. Persistent Research Notes
            conn.execute("""
                CREATE TABLE IF NOT EXISTS research_notes (
                    note_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    content_md TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
            """)
            conn.execute("INSERT INTO papers_fts(papers_fts) VALUES('rebuild');")
            conn.execute("INSERT INTO claims_fts(claims_fts) VALUES('rebuild');")
            conn.execute("INSERT INTO dead_ends_fts(dead_ends_fts) VALUES('rebuild');")
            conn.commit()

    @staticmethod
    def _build_fts_query(raw_query: str) -> str:
        """Sanitizes query and creates an OR-joined prefix search across tokens."""
        clean = re.sub(r'[^\w\s]', ' ', raw_query).strip()
        tokens = [t for t in clean.split() if t]
        if not tokens:
            return ""
        return " OR ".join(f'"{t}"*' for t in tokens)

    # -------------------------------------------------------------------------
    # Papers API
    # -------------------------------------------------------------------------
    def store_paper(self, paper: PaperRecord) -> bool:
        created_at = paper.created_at or time.time()
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO papers (
                    paper_id, title, authors_json, year, venue, abstract,
                    pdf_path, full_text_md, bibtex, citation_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                paper.paper_id,
                paper.title,
                json.dumps(paper.authors),
                paper.year,
                paper.venue,
                paper.abstract,
                paper.pdf_path,
                paper.full_text_md,
                paper.bibtex,
                paper.citation_count,
                created_at
            ))
            cur.execute("INSERT INTO papers_fts(papers_fts) VALUES('rebuild');")
            conn.commit()
            return True

    def search_papers(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        fts_query = self._build_fts_query(query)
        if not fts_query:
            return []

        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT p.paper_id, p.title, p.authors_json, p.year, p.venue, p.abstract,
                       p.citation_count, p.bibtex, bm25(papers_fts) as rank
                FROM papers_fts f
                JOIN papers p ON f.paper_id = p.paper_id
                WHERE papers_fts MATCH ?
                ORDER BY rank
                LIMIT ?;
            """, (fts_query, limit))
            rows = cur.fetchall()

            results = []
            for r in rows:
                results.append({
                    "paper_id": r["paper_id"],
                    "title": r["title"],
                    "authors": json.loads(r["authors_json"]),
                    "year": r["year"],
                    "venue": r["venue"],
                    "abstract": r["abstract"],
                    "citation_count": r["citation_count"],
                    "bibtex": r["bibtex"],
                    "bm25_score": round(abs(float(r["rank"])), 4)
                })
            return results

    # -------------------------------------------------------------------------
    # Claims API
    # -------------------------------------------------------------------------
    def store_claim(self, claim: ClaimRecord) -> bool:
        created_at = claim.created_at or time.time()
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO claims (
                    claim_id, paper_id, claim_text, section, quote_span,
                    verification_status, confidence, contradicting_claim_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                claim.claim_id,
                claim.paper_id,
                claim.claim_text,
                claim.section,
                claim.quote_span,
                claim.verification_status,
                claim.confidence,
                claim.contradicting_claim_id,
                created_at
            ))
            cur.execute("INSERT INTO claims_fts(claims_fts) VALUES('rebuild');")
            conn.commit()
            return True

    def query_claims(self, keyword: str, limit: int = 5) -> List[Dict[str, Any]]:
        fts_query = self._build_fts_query(keyword)
        if not fts_query:
            return []

        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT c.claim_id, c.paper_id, c.claim_text, c.section, c.quote_span,
                       c.verification_status, c.confidence, p.title as paper_title
                FROM claims_fts f
                JOIN claims c ON f.claim_id = c.claim_id
                JOIN papers p ON c.paper_id = p.paper_id
                WHERE claims_fts MATCH ?
                LIMIT ?;
            """, (fts_query, limit))
            return [dict(r) for r in cur.fetchall()]

    # -------------------------------------------------------------------------
    # Citation Graph API
    # -------------------------------------------------------------------------
    def add_citation(self, source_id: str, target_id: str, context: str = "", sentiment: str = "neutral") -> bool:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO citation_graph (source_paper_id, target_paper_id, context_snippet, sentiment, created_at)
                VALUES (?, ?, ?, ?, ?);
            """, (source_id, target_id, context, sentiment, time.time()))
            conn.commit()
            return True

    def get_citation_subgraph(self, paper_id: str, depth: int = 1) -> Dict[str, Any]:
        visited_nodes: Set[str] = {paper_id}
        edges: List[Dict[str, str]] = []
        frontier = {paper_id}

        with self._get_connection() as conn:
            for _ in range(depth):
                if not frontier:
                    break
                placeholders = ",".join("?" for _ in frontier)
                cur = conn.cursor()
                cur.execute(f"""
                    SELECT source_paper_id, target_paper_id, sentiment, context_snippet
                    FROM citation_graph
                    WHERE source_paper_id IN ({placeholders}) OR target_paper_id IN ({placeholders});
                """, list(frontier) + list(frontier))
                rows = cur.fetchall()

                next_frontier = set()
                for r in rows:
                    src, tgt = r["source_paper_id"], r["target_paper_id"]
                    edges.append({
                        "source": src,
                        "target": tgt,
                        "sentiment": r["sentiment"],
                        "context": r["context_snippet"]
                    })
                    if src not in visited_nodes:
                        visited_nodes.add(src)
                        next_frontier.add(src)
                    if tgt not in visited_nodes:
                        visited_nodes.add(tgt)
                        next_frontier.add(tgt)
                frontier = next_frontier

        return {"seed_paper_id": paper_id, "nodes": list(visited_nodes), "edges": edges}

    # -------------------------------------------------------------------------
    # Experiment & Dead-End Ledger API
    # -------------------------------------------------------------------------
    def record_experiment(self, exp: ExperimentRecord) -> bool:
        created_at = exp.created_at or time.time()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO experiments (
                    experiment_id, paper_id, name, hypothesis, commit_hash,
                    seed, config_json, metrics_json, status, reproduction_gap, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                exp.experiment_id,
                exp.paper_id,
                exp.name,
                exp.hypothesis,
                exp.commit_hash,
                exp.seed,
                json.dumps(exp.config),
                json.dumps(exp.metrics),
                exp.status,
                exp.reproduction_gap,
                created_at
            ))
            conn.commit()
            return True

    def record_dead_end(self, dead_end: DeadEndRecord) -> bool:
        created_at = dead_end.created_at or time.time()
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO dead_ends (
                    dead_end_id, hypothesis, failed_mechanism, compute_expended_hrs, root_cause, created_at
                ) VALUES (?, ?, ?, ?, ?, ?);
            """, (
                dead_end.dead_end_id,
                dead_end.hypothesis,
                dead_end.failed_mechanism,
                dead_end.compute_expended_hrs,
                dead_end.root_cause,
                created_at
            ))
            cur.execute("INSERT INTO dead_ends_fts(dead_ends_fts) VALUES('rebuild');")
            conn.commit()
            return True

    def query_dead_ends(self, concept_query: str) -> List[Dict[str, Any]]:
        fts_query = self._build_fts_query(concept_query)
        if not fts_query:
            return []

        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT d.dead_end_id, d.hypothesis, d.failed_mechanism, d.compute_expended_hrs, d.root_cause
                FROM dead_ends_fts f
                JOIN dead_ends d ON f.dead_end_id = d.dead_end_id
                WHERE dead_ends_fts MATCH ?;
            """, (fts_query,))
            return [dict(r) for r in cur.fetchall()]

    # -------------------------------------------------------------------------
    # Obsidian-Style Research Notes & WikiLink Sync
    # -------------------------------------------------------------------------
    def store_research_note(self, topic: str, content_md: str, tags: Optional[List[str]] = None) -> str:
        note_id = f"note_{hashlib.md5((topic + content_md).encode('utf-8')).hexdigest()[:10]}"
        tag_list = tags or re.findall(r"\[\[([^\]]+)\]\]", content_md)
        now = time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO research_notes (note_id, topic, content_md, tags_json, created_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (note_id, topic, content_md, json.dumps(tag_list), now),
            )
            conn.commit()

        # Mirror to Obsidian Research Vault
        obs_dir = Path("workspace/obsidian_vault/Research")
        obs_dir.mkdir(parents=True, exist_ok=True)
        safe_topic = re.sub(r"[^a-zA-Z0-9_\-\s]", "", topic).strip().replace(" ", "_") or note_id
        links_str = " ".join(f"[[{t}]]" for t in tag_list)
        md_payload = (
            f"---\nid: {note_id}\ntopic: {topic}\ntags: {json.dumps(tag_list)}\n---\n\n"
            f"# {topic}\n\n{content_md}\n\n## WikiLinks\n{links_str}\n"
        )
        (obs_dir / f"{safe_topic}.md").write_text(md_payload, encoding="utf-8")
        return note_id

    def search_research_notes(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        tokens = [t for t in re.findall(r"[A-Za-z0-9_]{3,}", query) if t]
        if not tokens:
            tokens = [query.strip()]
        clauses = " OR ".join(["(topic LIKE ? OR content_md LIKE ?)"] * len(tokens))
        params = []
        for t in tokens:
            params.extend([f"%{t}%", f"%{t}%"])
        params.append(limit)
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT note_id, topic, content_md, tags_json, created_at
                FROM research_notes
                WHERE {clauses}
                ORDER BY created_at DESC LIMIT ?;
                """,
                params,
            )
            return [
                {
                    "note_id": r["note_id"],
                    "topic": r["topic"],
                    "content_md": r["content_md"],
                    "tags": json.loads(r["tags_json"]),
                }
                for r in cur.fetchall()
            ]

