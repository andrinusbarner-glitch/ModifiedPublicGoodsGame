"""
Public Goods Game — Streamlit version
Run with:  streamlit run public_goods_game.py
Deploy free: https://share.streamlit.io

DATA LOGGING:
  - Google Sheets: automatic append on completion (needs setup, see below)
  - CSV download: always available as fallback
"""

import random
import time
import csv
import io
from datetime import datetime, timezone
from pathlib import Path
import streamlit as st

# ==========================================
# CONFIG
# ==========================================

NUM_ROUNDS = 5
NUM_PLAYERS = 5
ENDOWMENT = 5
MULTIPLIER = 1.2
POINTS_PER_BISCUIT = 5

# Biased random game grid, based on donations from the 3 baseline groups.
# One row per round; entry k is the probability that another player donates k (0-5).
DONATION_PROBABILITIES = [
    # Round 1
    [0.00, 0.20, 0.0667, 0.20, 0.3333, 0.20],
    # Round 2
    [0.0667, 0.00, 0.20, 0.1333, 0.20, 0.40],
    # Round 3
    [0.0667, 0.00, 0.1333, 0.20, 0.1333, 0.4667],
    # Round 4
    [0.0667, 0.20, 0.1333, 0.1333, 0.0667, 0.40],
    # Round 5
    [0.0667, 0.0667, 0.20, 0.20, 0.1333, 0.3333],
]

# ---------- Google Sheets config ----------
# 1. pip install gspread google-auth
# 2. Create a Google Cloud service account, download the JSON key
# 3. Share your Google Sheet with the service account email
# 4. Set these two values:
GOOGLE_SHEET_NAME = "Public Goods Game Data"       # name of your Google Sheet
GOOGLE_CREDENTIALS_FILE = "credentials.json"        # path to service account JSON
# If you don't want Google Sheets logging, just leave these as-is;
# the app will skip it gracefully and still offer CSV download.
# ------------------------------------------

st.set_page_config(page_title="Public Goods Game", page_icon="🎮", layout="centered")


# ==========================================
# GOOGLE SHEETS HELPER
# ==========================================

def append_to_google_sheet(row_data: dict):
    """Append one row to Google Sheets. Fails silently if not configured."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        # Deployed: credentials come from Streamlit secrets ([gcp_service_account]).
        # Local: fall back to the credentials.json file next to this script.
        if "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=scopes
            )
        else:
            creds = Credentials.from_service_account_file(
                str(Path(__file__).parent / GOOGLE_CREDENTIALS_FILE), scopes=scopes
            )
        client = gspread.authorize(creds)
        sheet = client.open(GOOGLE_SHEET_NAME).sheet1

        # If sheet is empty, write header row first
        if sheet.row_count == 0 or sheet.cell(1, 1).value is None:
            sheet.append_row(list(row_data.keys()))

        sheet.append_row(list(row_data.values()))
        return True

    except Exception as e:
        # Log but don't crash — CSV fallback is always available
        # repr so errors with an empty message (e.g. SpreadsheetNotFound) still show their type
        st.session_state.sheets_error = repr(e)
        return False


# ==========================================
# CSV HELPER
# ==========================================

def build_csv(row_data: dict) -> str:
    """Build a CSV string from one participant's data."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=row_data.keys())
    writer.writeheader()
    writer.writerow(row_data)
    return output.getvalue()


def build_row_data() -> dict:
    """Assemble one flat row from session state."""
    s = st.session_state
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": s.session_id,
        "treatment_fixed_value": s.fixed_value,
        "player_position": s.player_pos + 1,
        "fixed_position": s.fixed_pos + 1,
        "final_score": round(s.player_score, 2),
    }
    for i in range(NUM_ROUNDS):
        row[f"donation_r{i+1}"] = s.player_inputs[i]
        row[f"contributions_r{i+1}"] = str(s.rounds[i])
        row[f"winnings_r{i+1}"] = round(s.round_winnings[i], 2)
    return row


# ==========================================
# INITIALISE SESSION STATE
# ==========================================

def init_game():
    st.session_state.stage = "intro"
    st.session_state.current_round = 0
    st.session_state.show_feedback = False
    st.session_state.data_saved = False
    st.session_state.sheets_error = None
    st.session_state.session_id = f"{int(time.time())}_{random.randint(1000,9999)}"

    st.session_state.player_pos = random.randint(0, NUM_PLAYERS - 1)
    fixed_pos_options = [i for i in range(NUM_PLAYERS) if i != st.session_state.player_pos]
    st.session_state.fixed_pos = random.choice(fixed_pos_options)
    st.session_state.fixed_value = random.choice([0, 5])

    # New random grid of other players' donations every time the game starts
    st.session_state.base_grid = [
        random.choices(range(ENDOWMENT + 1), weights=probs, k=NUM_PLAYERS)
        for probs in DONATION_PROBABILITIES
    ]

    st.session_state.rounds = []
    st.session_state.player_inputs = []
    st.session_state.round_winnings = []
    st.session_state.player_score = 0.0


if "stage" not in st.session_state:
    init_game()


# ==========================================
# INTRO SCREEN
# ==========================================

if st.session_state.stage == "intro":
    st.markdown("## 🎮 Welcome to the Game")
    st.markdown("---")
    st.markdown("""
**Instructions**

You will now be anonymously linked with 4 other players.

- Each round, each of you will be assigned **5 points**.
- Each round you may donate between **0 and 5 points** to a public pool.
- The points in the pool will be multiplied by **1.2× and redistributed equally**.
- The redistributed points are added to the points you kept.
- Your goal is to **maximise your points**.
- You will be rewarded based on your total.

Good luck!
    """)

    if st.button("▶ Start Game", type="primary", use_container_width=True):
        with st.spinner("Searching for players..."):
            time.sleep(random.uniform(2, 4))
        st.session_state.stage = "playing"
        st.rerun()


# ==========================================
# PLAYING ROUNDS
# ==========================================

elif st.session_state.stage == "playing":
    r = st.session_state.current_round

    st.markdown(f"### Round {r + 1} of {NUM_ROUNDS}")
    st.markdown("---")

    # ---------- INPUT PHASE ----------
    if not st.session_state.show_feedback:
        donation = st.slider(
            f"How many of your {ENDOWMENT} points do you donate to the pool?",
            min_value=0, max_value=ENDOWMENT, value=0, step=1,
            key=f"donation_{r}"
        )

        if st.button("Submit", type="primary", use_container_width=True):
            contributions = list(st.session_state.base_grid[r])
            contributions[st.session_state.player_pos] = donation
            contributions[st.session_state.fixed_pos] = st.session_state.fixed_value

            pool = sum(contributions)
            winnings = (pool * MULTIPLIER) / NUM_PLAYERS
            points_kept = ENDOWMENT - donation
            round_score = points_kept + winnings

            st.session_state.rounds.append(contributions)
            st.session_state.player_inputs.append(donation)
            st.session_state.round_winnings.append(winnings)
            st.session_state.player_score += round_score

            with st.spinner("Waiting for other players..."):
                time.sleep(random.uniform(1, 4))

            st.session_state.show_feedback = True
            st.rerun()

    # ---------- FEEDBACK PHASE ----------
    else:
        contributions = st.session_state.rounds[r]
        donation = st.session_state.player_inputs[r]
        winnings = st.session_state.round_winnings[r]
        points_kept = ENDOWMENT - donation
        pool = sum(contributions)
        average = pool / NUM_PLAYERS

        st.markdown(f"**All contributions:** {contributions}")
        st.markdown(f"**Pool total:** {pool}  |  **Average donation:** {average:.2f}")
        st.markdown(f"**Your share from pool:** {winnings:.2f}")
        st.markdown(f"**Points kept:** {points_kept}  |  **Round score:** {points_kept + winnings:.2f}")
        st.markdown(f"**Running total:** {st.session_state.player_score:.2f}")

        if r + 1 < NUM_ROUNDS:
            if st.button("Next Round →", type="primary", use_container_width=True):
                st.session_state.current_round += 1
                st.session_state.show_feedback = False
                st.rerun()
        else:
            if st.button("See Final Results →", type="primary", use_container_width=True):
                st.session_state.stage = "results"
                st.rerun()


# ==========================================
# RESULTS SCREEN
# ==========================================

elif st.session_state.stage == "results":
    st.markdown("## 🏆 All Rounds Completed!")
    st.markdown("---")

    for i, (contribs, w) in enumerate(
        zip(st.session_state.rounds, st.session_state.round_winnings), start=1
    ):
        st.markdown(f"**Round {i}:** {contribs}  →  share = {w:.2f}")

    st.markdown("---")
    st.markdown(f"### Your Final Score: **{st.session_state.player_score:.2f}**")
    st.markdown("Thanks for playing!")
    biscuits = round(st.session_state.player_score / POINTS_PER_BISCUIT)
    st.markdown(f"### 🍪 Congratulations, you won: **{biscuits} biscuits**")

    # ---------- AUTO-SAVE TO GOOGLE SHEETS ----------
    row_data = build_row_data()

    if not st.session_state.data_saved:
        success = append_to_google_sheet(row_data)
        st.session_state.data_saved = True

        if success:
            st.success("✅ Response saved.")
        # If Sheets failed, don't show error to participant — just offer CSV

    # ---------- CSV DOWNLOAD (always available) ----------
    csv_string = build_csv(row_data)
    st.download_button(
        label="📥 Download your data (CSV)",
        data=csv_string,
        file_name=f"pgg_{st.session_state.session_id}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    # ---------- EXPERIMENTER DEBUG ----------
    with st.expander("Experimenter info (hidden from participants)"):
        st.write(f"Session ID: {st.session_state.session_id}")
        st.write(f"Player position: {st.session_state.player_pos + 1}")
        st.write(f"Fixed position: {st.session_state.fixed_pos + 1}")
        st.write(f"Fixed value (treatment): {st.session_state.fixed_value}")
        st.write(f"Player inputs: {st.session_state.player_inputs}")
        if st.session_state.sheets_error:
            st.warning(f"Google Sheets error: {st.session_state.sheets_error}")

    if st.button("🔄 Play Again", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
