"""Streamlit front-end for HR users. It only talks to the HTTP API."""

from __future__ import annotations

import hmac
import os
import time

import httpx
import streamlit as st

API_URL = os.environ.get("CVSEARCH_API_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("CVSEARCH_API_KEY", "")
UI_PASSWORD = os.environ.get("CVSEARCH_UI_PASSWORD", "")
ICON = {"met": "✅", "partial": "🟡", "not_met": "❌"}
EXAMPLES = [
    "Data Scientist senior avec expérience en IA générative et déploiement cloud (Azure ou GCP)",
    "Profil ayant développé des chatbots",
    "Data Ingénieur qui concoit des datas platforms sur AWS ou Azure",
    "Chef de projet avec de l'expérience en cadrage de projet",
    "Directeur Marketing avec au moins 10 ans d'expérience dans le conseil",
]


def api(method: str, path: str, **kwargs: object) -> httpx.Response:
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    response = httpx.request(method, f"{API_URL}{path}", headers=headers, timeout=180, **kwargs)  # type: ignore[arg-type]
    response.raise_for_status()
    return response


def login_gate() -> None:
    """Shared-password gate; the API itself is protected by its own key."""
    if not UI_PASSWORD or st.session_state.get("authenticated"):
        return
    st.title("CV Search")
    password = st.text_input("Mot de passe", type="password")
    if password and hmac.compare_digest(password, UI_PASSWORD):
        st.session_state["authenticated"] = True
        st.rerun()
    elif password:
        st.error("Mot de passe incorrect")
    st.stop()


def render_hit(rank: int, hit: dict) -> None:  # type: ignore[type-arg]
    badge = (
        "Correspondance complète"
        if hit["fully_matching"]
        else f"{hit['unmet_musts']} critère(s) obligatoire(s) non couvert(s)"
    )
    seniority = hit["seniority"] or "n/c"
    title = f"#{rank} · {hit['full_name']} — {hit['current_title'] or ''}"
    with st.expander(f"{title} · {seniority} · score {hit['score']:.0%} · {badge}"):
        st.write(hit["summary"])
        basis = {"positions": "calculé depuis les dates", "stated": "déclaré sur le CV", "title": "déduit du titre"}
        st.caption(f"{hit['years_of_experience']} ans d'expérience ({basis.get(hit['experience_basis'], 'inconnu')})")
        for criterion in hit["criteria"]:
            origin = "règle" if criterion["checked_by"] == "rules" else "LLM"
            st.markdown(
                f"{ICON[criterion['verdict']]} **{criterion['criterion']}** _({origin})_  \n{criterion['evidence']}"
            )
        if hit["matched_passage"]:
            st.caption(f"Passage le plus proche : {hit['matched_passage'][:300]}")


def search_tab() -> None:
    query = st.text_area("Décrivez le profil recherché", value=st.session_state.get("query", ""), height=80)
    st.caption("Exemples : " + " · ".join(f"`{e[:45]}…`" for e in EXAMPLES[:3]))
    top_k = st.slider("Nombre de profils", 1, 10, 5)
    if st.button("Rechercher", type="primary", disabled=len(query.strip()) < 3):
        with st.spinner("Analyse de la demande et évaluation des profils…"):
            try:
                result = api("POST", "/search", json={"query": query, "top_k": top_k}).json()
            except httpx.HTTPError as exc:
                st.error(f"Erreur API : {exc}")
                return
        st.markdown(
            "**Critères retenus :** "
            + " · ".join(
                f"{c['label']} ({'obligatoire' if c['importance'] == 'must' else 'souhaité'})"
                for c in result["interpreted_as"]["criteria"]
            )
        )
        if result["no_full_match"]:
            st.warning("Aucun profil ne remplit tous les critères obligatoires. Voici les profils les plus proches.")
        for rank, hit in enumerate(result["hits"], start=1):
            render_hit(rank, hit)


def ingest_tab() -> None:
    uploads = st.file_uploader("CV (PDF, DOCX, PPTX)", type=["pdf", "docx", "pptx"], accept_multiple_files=True)
    if st.button("Importer", disabled=not uploads):
        files = [("files", (u.name, u.getvalue())) for u in uploads]
        for item in api("POST", "/cvs", files=files).json():
            st.write(f"{'⏭️ déjà importé' if item['duplicate'] else '📥 en file'} — {item['filename']}")
    st.subheader("CV importés")
    if st.button("Actualiser"):
        st.rerun()
    rows = api("GET", "/cvs").json()
    st.dataframe(
        [
            {
                "fichier": r["filename"],
                "statut": r["status"],
                "nom": r["full_name"],
                "séniorité": r["seniority"],
                "erreur": r["error"],
            }
            for r in rows
        ],
        use_container_width=True,
    )
    if any(r["status"] in {"queued", "processing"} for r in rows):
        time.sleep(3)
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="CV Search", page_icon="🔎", layout="wide")
    login_gate()
    st.title("🔎 CV Search")
    search, ingest = st.tabs(["Recherche", "Import de CV"])
    with search:
        search_tab()
    with ingest:
        ingest_tab()


main()
