import streamlit as st
import os
import sys
from dotenv import load_dotenv


# ──────────────────────────────────────────────────────────────────────────────
# Ensure project root is on sys.path so that "resume_analyzer" can be imported
# ──────────────────────────────────────────────────────────────────────────────
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from resume_analyzer.ingestion.ingest_pg import ingest_all_resumes, load_env_vars
from resume_analyzer.ingestion.helpers import (
    connect_postgres,
    ensure_resumes_table,
    upsert_resume_metadata,
)
from resume_analyzer.backend.model import Qwen2VLClient
load_dotenv()  # In case helpers need environment variables
# ──────────────────────────────────────────────────────────────────────────────
# CHAT INTERFACE MODE
# ──────────────────────────────────────────────────────────────────────────────
params = st.experimental_get_query_params()
selected_files = params.get("files", None)
if selected_files:
    st.set_page_config(page_title="💬 Resume Chat", layout="wide")
    st.title("💬 Chat about filtered resumes")
    st.subheader("Files in context:")
    for fn in selected_files:
        st.markdown(f"- **{fn}**")

    # init your LLM client (reuse the same one you built for ingest)
    qwen_client = Qwen2VLClient(
        host="http://localhost", port=8001,
        model="Qwen/Qwen2.5-VL-7B-Instruct",
        temperature=0.7
    )

    # initialize chat history
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []  # list of {"role":"user"/"assistant", "content":...}

    # render the existing messages
    for msg in st.session_state.chat_history:
        st.chat_message(msg["role"]).write(msg["content"])

    # get new user input
    user_prompt = st.chat_input("Ask me anything about these resumes…")
    if user_prompt:
        # add user message
        st.session_state.chat_history.append({"role": "user", "content": user_prompt})
        st.chat_message("user").write(user_prompt)

        # prepare a system prompt explaining the context
        system_prompt = f"""
        You are an expert HR assistant.  I have the following resumes:
        {', '.join(selected_files)}

        Answer user questions by referring only to those resumes.  If you don't know, say so.
        """

        # call Qwen (or any chat LLM you prefer)
        assistant_reply = qwen_client.chat_completion(
            question=user_prompt,
            system_prompt=system_prompt
        ).strip()

        # add and display assistant reply
        st.session_state.chat_history.append({"role": "assistant", "content": assistant_reply})
        st.chat_message("assistant").write(assistant_reply)

    st.stop()  # do not run the rest of the app when in chat mode
