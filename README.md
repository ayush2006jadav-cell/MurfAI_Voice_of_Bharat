# 🏥 Swasthya Bharat (સ્વાસ્થ્ય ભારત) — AI Voice Assistant for Health Access

> **Bridging the healthcare gap across India with ultra-fast, bilingual AI voice assistance in Gujarati (ગુજરાતી) and English.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Murf Falcon](https://img.shields.io/badge/TTS-Murf%20Falcon%20(55ms)-6366F1)](https://murf.ai/api/docs/text-to-speech/streaming)
[![LiveKit](https://img.shields.io/badge/Transport-LiveKit-002cf2)](https://docs.livekit.io)
[![Deepgram](https://img.shields.io/badge/STT-Deepgram%20Nova--3-13EF95)](https://deepgram.com)
[![Gemini](https://img.shields.io/badge/LLM-Gemini%203.5%20Flash-4285F4)](https://aistudio.google.com)
[![TypeScript](https://img.shields.io/badge/Frontend-Next.js%20%2F%20TypeScript-007ACC?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Python](https://img.shields.io/badge/Backend-Python%203.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)

---

## 📌 Overview

**Swasthya Bharat (સ્વાસ્થ્ય ભારત)** is a production-ready, real-time voice AI assistant designed to democratize **Healthcare Access** for Indian citizens. By combining **Murf Falcon TTS** (the fastest voice synthesis engine on the market), **Deepgram Nova-3 STT**, **Google Gemini 3.5**, and **LiveKit Agents**, Swasthya Bharat enables hands-free, natural conversational queries in regional languages.

Citizens can ask questions in **Gujarati** or **English** to navigate government health initiatives, locate public health facilities, check scheme eligibility, and understand routine care processes without needing literacy in complex medical portal interfaces.

---

## 🌟 Key Features

- 📜 **Government Health Schemes**: Quick guidance on **Ayushman Bharat PM-JAY** (eligibility, ₹5 Lakh family cover, card application, and empaneled hospitals).
- 🆔 **ABHA Health ID Registration**: Step-by-step assistance for creating Ayushman Bharat Health Account (ABHA) digital health IDs.
- 🏥 **Health Facility Finder**: Helps users locate nearby Government Hospitals, Primary Health Centers (PHCs), and Community Health Centers (CHCs).
- 👶 **Maternal & Immunization Care**: Information on maternal care, child vaccination schedules, and general preventative wellness.
- 🗣️ **Native Gujarati & English Bilingual Interface**: Seamlessly understands and responds in authentic Gujarati (ગુજરાતી), English, or mixed Gujlish conversations.
- ⚡ **Sub-Second Latency**: Powered by **Murf Falcon TTS** (55ms latency) and LiveKit WebRTC streaming for immediate, human-like responses.
- 🛡️ **Safety & Responsible AI**: Built-in strict medical disclaimers with emergency escalation protocols (redirecting medical diagnoses/emergencies to doctors and 108 emergency services).

---

## 🏗️ System Architecture

```mermaid
flowchart LR
    A[🎙️ Citizen Speaks<br/><i>Gujarati / English</i>] -->|WebRTC Audio Stream| B[Deepgram Nova-3 STT<br/><i>Multilingual Speech-to-Text</i>]
    B -->|Transcribed Text| C[Google Gemini 3.5 LLM<br/><i>Swasthya Bharat Agent Logic</i>]
    C -->|Response Text| D[Murf Falcon TTS<br/><i>Anisha Voice (55ms Latency)</i>]
    D -->|Synthesized Audio| E[LiveKit Real-Time Engine]
    E -->|Low-Latency Stream| F[🔊 Citizen Hears<br/><i>Natural Voice Response</i>]

    style A fill:#1e293b,stroke:#64748b,color:#fff
    style B fill:#0f766e,stroke:#14b8a6,color:#fff
    style C fill:#4338ca,stroke:#6366f1,color:#fff
    style D fill:#0369a1,stroke:#0ea5e9,color:#fff
    style E fill:#c2410c,stroke:#f97316,color:#fff
    style F fill:#1e293b,stroke:#64748b,color:#fff
```

---

## 🗣️ Sample Conversations

<details open>
<summary><b>1. PM-JAY & Ayushman Card Inquiry (Gujarati)</b></summary>

> **User:** *"નમસ્તે, આયુષ્માન કાર્ડ કેવી રીતે બનાવવું અને તેમાં શું લાભ મળે?"*  
> **Swasthya Bharat Agent:** *"નમસ્તે! આયુષ્માન ભારત PM-JAY કાર્ડ હેઠળ દરેક પરિવારને વર્ષે ₹5 લાખ સુધીની મફત સારવાર મળે છે. તમે નજીકના સરકારી હોસ્પિટલ અથવા સીએસસી સેન્ટર પર રેશન કાર્ડ અને આધાર કાર્ડ લઈને જઈ શકો છો."*
</details>

<details>
<summary><b>2. Locating PHC & Child Immunization (English / Gujlish)</b></summary>

> **User:** *"Where is the nearest PHC center and what vaccines are needed for 6-month-old baby?"*  
> **Swasthya Bharat Agent:** *"You can find your nearest Primary Health Center (PHC) at your local taluka hospital or district health department. For a 6-month-old baby, routine vaccines include Pentavalent and Oral Polio Vaccine. Please consult your local PHC nurse or doctor for exact scheduling."*
</details>

<details>
<summary><b>3. Medical Disclaimer & Emergency Safety (Gujarati)</b></summary>

> **User:** *"મને ખૂબ છાતીમાં દુખાવો થાય છે, મને કઈ દવા લેવી જોઈએ?"*  
> **Swasthya Bharat Agent:** *"હું એઆઈ આસિસ્ટન્ટ છું, ડૉક્ટર નથી. જો તમને છાતીમાં દુખાવો થતો હોય તો કૃપા કરીને તરત જ નજીકના ડૉક્ટરનો સંપર્ક કરો અથવા 108 પર કૉલ કરીને ઇમરજન્સી મદદ લો."*
</details>

---

## 🚀 Quickstart Guide

### Prerequisites

- **Python** 3.10 or higher
- **[uv](https://docs.astral.sh/uv/)** — High-performance Python package manager
  ```bash
  # macOS / Linux
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # Windows (PowerShell)
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- **Node.js** 18+ & **pnpm**
  ```bash
  npm install -g pnpm
  ```
- A free [LiveKit Cloud](https://cloud.livekit.io/) account

---

### Step 1: Clone the Repository

```bash
git clone https://github.com/ayush2006jadav-cell/MurfAI_Voice_of_Bharat.git
cd VoiceForBharat-main
```

---

### Step 2: Environment Setup

Create `.env.local` files in both `backend/` and `frontend/` directories:

#### `backend/.env.local`
```env
LIVEKIT_URL=wss://your-livekit-project.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
MURF_API_KEY=your_murf_api_key
DEEPGRAM_API_KEY=your_deepgram_api_key
GOOGLE_API_KEY=your_google_gemini_api_key
```

#### `frontend/.env.local`
```env
LIVEKIT_URL=wss://your-livekit-project.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
AGENT_NAME=my-agent
```

---

### Step 3: Install & Run Backend

```bash
cd backend
uv sync
uv run python src/agent.py download-files   # Download VAD & Turn Detector models (first time only)
uv run python src/agent.py dev              # Start agent in development mode
```

---

### Step 4: Install & Run Frontend

In a new terminal window:

```bash
cd frontend
pnpm install
pnpm dev
```

Open **`http://localhost:3000`** in your browser, click **"Start Talking / વાત શરૂ કરો"**, allow microphone access, and begin speaking!

---

### Step 5: All-In-One Launcher (Optional)

Alternatively, run all services simultaneously using the root scripts:

```bash
# Windows (PowerShell)
.\start_app.ps1

# macOS / Linux
chmod +x start_app.sh
./start_app.sh
```

---

## ⚙️ Configuration & Customization

All core agent parameters are configured in [`backend/src/agent.py`](./backend/src/agent.py) and [`frontend/app-config.ts`](./frontend/app-config.ts).

### 🎙️ Changing Voice & Persona

- **Murf Voice**: Managed via `murf.TTS(voice="Anisha", style="Conversation", ...)` in `agent.py`. Explore all voices at [Murf Voice Library](https://murf.ai/api/docs/voices-styles/voice-library).
- **System Prompt**: Edit `SYSTEM_PROMPT` in `agent.py` to add new health categories, local dialects, or hospital databases.

### 🧠 LLM & Speech Engines

- **STT**: Deepgram Nova-3 (`deepgram.STT(model="nova-3", language="multi")`) for Gujarati and English.
- **LLM**: Google Gemini 3.5 Flash-Lite (`google.LLM(model="gemini-3.5-flash-lite")`).

---

## 📂 Repository Structure

```
VoiceForBharat/
├── backend/                 # Python Voice Agent
│   ├── src/
│   │   └── agent.py         # Swasthya Bharat System Prompt, Murf TTS & LiveKit pipeline
│   ├── tests/               # LLM-judged evaluation tests (pytest)
│   ├── .env.example         # Backend environment variables template
│   ├── pyproject.toml       # Python dependencies (uv)
│   └── railway.toml         # Deployment configuration for Railway
├── frontend/                # Next.js Voice Web App
│   ├── app/                 # Next.js app router & token endpoints
│   ├── components/          # Voice UI components & audio visualizer
│   ├── app-config.ts        # Health theme branding & visualizer config
│   ├── .env.example         # Frontend environment variables template
│   └── package.json         # Node.js dependencies (pnpm)
├── start_app.ps1            # Windows single-command launcher
├── start_app.sh             # Linux/macOS single-command launcher
└── README.md                # Project documentation
```

---

## 🧪 Testing & Evaluation

The backend includes an LLM-as-judge test suite built on LiveKit's testing framework:

```bash
cd backend
uv run pytest
```

Tests evaluate critical agent behaviors including welcoming users in Gujarati/English, upholding medical disclaimers, and accurately providing PM-JAY scheme details.

---

## 🌐 Deployment Guide

| Service | Platform | Deploy Link / Instructions |
| :--- | :--- | :--- |
| **Backend Agent** | **Railway / Docker** | [![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy) <br/> Deploy as a background Python worker connecting to LiveKit. |
| **Frontend UI** | **Vercel** | [![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new) <br/> Deploy Next.js app with `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET`. |

---

## 🔗 Official Documentation & References

- 🎙️ [Murf Falcon TTS Documentation](https://murf.ai/api/docs/text-to-speech/streaming)
- 🔊 [Murf Voice Library](https://murf.ai/api/docs/voices-styles/voice-library)
- ⚡ [LiveKit Agents SDK](https://docs.livekit.io/agents)
- 📝 [Deepgram Speech Recognition](https://developers.deepgram.com)
- 🤖 [Google Gemini AI](https://ai.google.dev/)
- 🏥 [Ayushman Bharat PM-JAY Portal](https://pmjay.gov.in/)
- 🗺️ [OpenStreetMap](https://www.openstreetmap.org/) (Data source for nearby healthcare facility lookup — © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright))
- ⚡ [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API) (Real-time geographic query API for OSM healthcare data)
- 📍 [OpenStreetMap Nominatim](https://nominatim.openstreetmap.org/) (Geocoding engine for location name resolution)

---

## 🗺️ Real Healthcare Facility Lookup (OpenStreetMap & Overpass API)

Swasthya Bharat includes a real-domain function tool (`find_nearest_healthcare_facility`) that queries live geographic data directly from **OpenStreetMap** using the **Overpass API**.

### Key Capabilities:
- **Real-Time Data**: Queries real OSM nodes, ways, and relations for `amenity=hospital`, `amenity=clinic`, `amenity=doctors`, `amenity=health_post`, and `healthcare=*` tags.
- **Geocoding Support**: Uses OpenStreetMap Nominatim to resolve place names (e.g., "Ahmedabad", "Surat", "Paldi") to precise latitude and longitude coordinates when GPS coordinates are unavailable.
- **Geographic Distance Calculation**: Computes exact great-circle distance using the Haversine formula and returns the nearest facilities sorted by distance.
- **Data Freshness & Disclaimers**: Includes data retrieval timestamps (`queried_at`) and OSM data timestamps (`data_timestamp`). Advises users that data is community-maintained and should be verified before travelling.
- **Privacy & Safety First**: Coordinates and full addresses are **never** saved to persistent SQLite caller memory, and emergency safety rules strictly take precedence.

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](./LICENSE) for more information.