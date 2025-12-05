import streamlit as st
import google.generativeai as genai
from google.generativeai.types import GenerationConfig, HarmCategory, HarmBlockThreshold
import json
import os
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# 0. 초기 설정 및 보안 검사
# ==========================================
st.set_page_config(page_title="Eternal Memory Chat", layout="wide")

def check_password():
    if "PASSWORD" not in st.secrets["general"]:
        st.error("Secrets에 PASSWORD가 없습니다.")
        return False
    
    def password_entered():
        if st.session_state["password"] == st.secrets["general"]["PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("🔒 비밀번호", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("🔒 비밀번호", type="password", on_change=password_entered, key="password")
        st.error("비밀번호 불일치")
        return False
    return True

if not check_password(): st.stop()

try:
    genai.configure(api_key=st.secrets["general"]["GOOGLE_API_KEY"])
except:
    st.error("Secrets에 GOOGLE_API_KEY가 없습니다."); st.stop()

# ==========================================
# [핵심] 구글 시트 데이터베이스 연결 (DB)
# ==========================================
@st.cache_resource
def init_sheet_connection():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = json.loads(st.secrets["gcp"]["info"], strict=False)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet_id = st.secrets["general"]["SHEET_ID"]
    return client.open_by_key(sheet_id).sheet1

try:
    SHEET = init_sheet_connection()
except Exception as e:
    st.error(f"구글 시트 연결 실패! 설정 확인 필요.\n{e}"); st.stop()

# ==========================================
# [데이터 핸들링] 저장 / 로드 / 삭제
# ==========================================
CHUNK_SIZE = 40000 

def load_json(folder, filename):
    full_key = f"{folder}/{filename}"
    try:
        cell = SHEET.find(full_key, in_column=1)
        if cell:
            row_values = SHEET.row_values(cell.row)
            if len(row_values) > 1:
                return json.loads("".join(row_values[1:]))
    except Exception as e:
        print(f"Load Error ({full_key}): {e}")
    return {}

def save_json(folder, filename, data):
    full_key = f"{folder}/{filename}"
    try:
        data_str = json.dumps(data, ensure_ascii=False)
        chunks = [data_str[i:i+CHUNK_SIZE] for i in range(0, len(data_str), CHUNK_SIZE)]
        row_data = [full_key] + chunks
        
        cell = SHEET.find(full_key, in_column=1)
        if cell:
            if len(row_data) > SHEET.col_count: SHEET.resize(cols=len(row_data) + 5)
            SHEET.update(range_name=f"A{cell.row}", values=[row_data])
        else:
            SHEET.append_row(row_data)
    except Exception as e:
        st.toast(f"저장 중 문제 발생: {e}") 
        print(f"Save Error {full_key}: {e}")

# [신규 기능] 삭제 함수 추가
def delete_json(folder, filename):
    full_key = f"{folder}/{filename}"
    try:
        cell = SHEET.find(full_key, in_column=1)
        if cell:
            SHEET.delete_rows(cell.row) # 해당 줄을 삭제
            return True
    except Exception as e:
        st.error(f"삭제 실패: {e}")
    return False

# ==========================================
# 설정 및 모델 로드
# ==========================================
DEFAULT_CONFIG = {  
    "chat_model": "models/gemini-1.5-pro",  
    "memory_model": "models/gemini-1.5-flash",  
    "memory_level": "Standard (10,000자)",  
    "temperature": 1.0,    
    "top_p": 0.95,         
    "max_tokens": 8192,  
    "last_user_id": "default",  
    "last_char_id": ""  
}

def load_config():
    data = load_json("config", "main.json")
    return data if data else DEFAULT_CONFIG

def update_config(key, value):
    curr = load_config()
    curr[key] = value
    save_json("config", "main.json", curr)

def save_advanced_config(chat, mem, lev, temp, top, tok):
    curr = load_config()
    curr.update({"chat_model":chat, "memory_model":mem, "memory_level":lev, 
                 "temperature":temp, "top_p":top, "max_tokens":tok})
    save_json("config", "main.json", curr)

# ==========================================
# 데이터 로더
# ==========================================
def get_all_data_optimized():
    try: return SHEET.get_all_values() 
    except: return []

def load_characters():
    rows = get_all_data_optimized()
    db = {}
    for r in rows:
        if not r: continue
        fname = r[0]
        if fname.startswith('characters/') and fname.endswith('.json'):
            cid = fname.split('/')[-1].replace('.json', '')
            try:
                full_content = "".join(r[1:]) 
                if not full_content: continue
                data = json.loads(full_content)
                for k in ["name","description","system_prompt","first_message","image"]: data.setdefault(k,"")
                data.setdefault("lorebooks", [])
                db[cid] = data
            except: pass
    return db

def load_users():
    rows = get_all_data_optimized()
    db = {}
    for r in rows:
        if not r: continue
        fname = r[0]
        if fname.startswith('users/') and fname.endswith('.json'):
            uid = fname.split('/')[-1].replace('.json', '')
            try: 
                full = "".join(r[1:])
                db[uid] = json.loads(full)
            except: pass
    if not db:
        def_u = {"name": "User", "gender": "?", "age": "?", "profile": "Traveler"}
        db["default"] = def_u
    return db

def load_memory(char_id):
    mem = load_json("memory", f"{char_id}.json")
    return mem if mem else {"summary": "기록 없음", "recent_event": "", "location": "알 수 없음", "relations": ""}

def load_user_note(char_id): return load_json("usernotes", f"{char_id}.json").get("content", "")
def save_user_note(char_id, content): save_json("usernotes", f"{char_id}.json", {"content": content})

# 로직 함수
def trigger_lorebooks(text, lorebooks):
    act = []
    text = text.lower()
    for b in lorebooks:
        tags = [t.strip().lower() for t in b.get("tags", "").split(",") if t.strip()]
        for tag in tags:
            if tag in text: act.append(b.get("content", "")); break
    return "\n[Active Lorebook]\n" + "\n".join(act[:5]) + "\n" if act else ""

def generate_response(chat_model_id, prompt_temp, c_char, c_user, mem, lore, history, user_note, temperature, top_p, max_tokens):
    chat_model = genai.GenerativeModel(chat_model_id)
    gen_config = GenerationConfig(temperature=temperature, top_p=top_p, max_output_tokens=max_tokens)
    safety = {HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}
    
    recent = history[-1]['content'] if history and history[-1]['role'] == 'user' else ""
    ctx = "\n".join([m['content'] for m in history[-5:]])
    active_lore = trigger_lorebooks(ctx + recent, c_char.get("lorebooks", []))
    sys = f"""
    [Situation] Roleplay Chat
    [Target Character] {c_char['name']}: {c_char['description']}
    [System Instruction] {c_char['system_prompt']}
    [Current User Persona] Name: {c_user['name']}, Gender: {c_user.get('gender')}, Age: {c_user.get('age')}
    [User Profile] {c_user.get('profile')}
    [User Note] {user_note}
    [Memory] {mem.get('summary')}
    {mem.get('recent_event')}
    {active_lore}"""
    full = f"System: {sys}\n" + "\n".join([f"{m['role']}: {m['content']}" for m in history])
    return chat_model.generate_content(full, generation_config=gen_config, safety_settings=safety).text

# ==========================================
# 메인 UI
# ==========================================
try:
    CHARACTER_DB = load_characters()
    USER_DB = load_users()
    current_config = load_config()
except Exception as e:
    st.error(f"데이터 로드 에러: {e}"); st.stop()

with st.sidebar:
    st.title("☁️ 클라우드 메모리 챗봇")
    st.caption("삭제 기능 추가됨")
    
    try: av_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]; av_models.sort()
    except: av_models = ["models/gemini-1.5-flash"]
    try: ic = av_models.index(current_config.get("chat_model"))
    except: ic = 0
    chat_model_id = st.selectbox("모델", av_models, index=ic)
    if chat_model_id != current_config.get("chat_model"):
        save_advanced_config(chat_model_id, current_config.get("memory_model", av_models[0]), "Standard", 1.0, 0.95, 8192)
        st.rerun()
    st.divider()
    
    if CHARACTER_DB:
        char_options = list(CHARACTER_DB.keys())
        saved_cid = current_config.get("last_char_id", "")
        if saved_cid not in char_options: saved_cid = char_options[0]
        try: default_cid_idx = char_options.index(saved_cid)
        except: default_cid_idx = 0
        sel_cid = st.selectbox("🤖 캐릭터 선택", char_options, index=default_cid_idx, format_func=lambda x: CHARACTER_DB[x]["name"])
        if sel_cid != current_config.get("last_char_id", ""):
            update_config("last_char_id", sel_cid); st.rerun()  
        curr_char = CHARACTER_DB[sel_cid]
    else:
        st.info("Studio에서 캐릭터를 만드세요."); curr_char = None; sel_cid = None

    user_options = list(USER_DB.keys())
    saved_uid = current_config.get("last_user_id", "")
    if saved_uid not in user_options and user_options: saved_uid = user_options[0]
    if user_options:
        try: ui = user_options.index(saved_uid)
        except: ui = 0
        sel_uid = st.selectbox("👤 내 페르소나 선택", user_options, index=ui, format_func=lambda x: USER_DB[x]["name"])
        if sel_uid != current_config.get("last_user_id", ""): 
            update_config("last_user_id", sel_uid); st.rerun()
        curr_user = USER_DB[sel_uid]
    else:
        curr_user = {"name": "User", "gender": "?", "age": "?", "profile": "New Traveler"}
        sel_uid = "default"

    st.divider()
    if st.button("🔄 새로고침"): st.rerun()

# 탭 구성
tab1, tab2, tab3 = st.tabs(["💬 대화", "🧠 기억", "✏️ 스튜디오"])

if sel_cid:
    sess_key = f"hist_{sel_cid}"
    if sess_key not in st.session_state:
        hf = load_json("history", f"{sel_cid}.json")
        if not hf and curr_char.get("first_message"):
            hf = [{"role": "assistant", "content": curr_char["first_message"]}]
            save_json("history", f"{sel_cid}.json", hf)
        st.session_state[sess_key] = hf if hf else []
    
    mem_data = load_memory(sel_cid)
    u_note = load_user_note(sel_cid)

    with tab1:
        for m in st.session_state[sess_key]:
            with st.chat_message(m["role"]): st.markdown(m["content"])
        
        if p := st.chat_input(f"{curr_user['name']} (으)로 대화 중..."):
            st.session_state[sess_key].append({"role":"user", "content":p})
            save_json("history", f"{sel_cid}.json", st.session_state[sess_key]) 
            try:
                r = generate_response(chat_model_id, "", curr_char, curr_user, mem_data, curr_char.get("lorebooks",[]), st.session_state[sess_key], u_note, 1.0, 0.95, 8192)
                st.session_state[sess_key].append({"role":"assistant", "content":r})
                save_json("history", f"{sel_cid}.json", st.session_state[sess_key]) 
                st.rerun()
            except Exception as e: st.error(f"오류: {e}")

    with tab2:
        st.subheader("DB 기억 & 노트")
        st.json(mem_data)
        st.text_area("유저 노트", value=u_note, key="u_note_input")
        if st.button("노트 저장"):
            save_user_note(sel_cid, st.session_state["u_note_input"]); st.success("저장됨")
        if st.button("대화 초기화 (새 시즌)"):
            st.session_state[sess_key] = []
            save_json("history", f"{sel_cid}.json", []); st.rerun()

    with tab3:
        col1, col2 = st.columns(2)
        
        # --- 왼쪽: 캐릭터 관리 ---
        with col1:
            st.subheader("🤖 캐릭터 관리")
            mode_char = st.radio("작업 모드", ["기존 캐릭터 수정", "새 캐릭터 생성"], key="mode_char", horizontal=True)
            
            if mode_char == "기존 캐릭터 수정" and curr_char:
                c_id_val, c_name_val = sel_cid, curr_char['name']
                c_desc_val, c_msg_val = curr_char['description'], curr_char['first_message']
                c_sys_val, c_btn_txt, c_id_disable = curr_char['system_prompt'], "수정사항 저장", True
            else:
                c_id_val, c_name_val, c_desc_val, c_msg_val, c_sys_val = "", "", "", "", ""
                c_btn_txt, c_id_disable = "새 캐릭터 생성", False
            
            ncid = st.text_input("캐릭터 ID", value=c_id_val, disabled=c_id_disable)
            ncnm = st.text_input("캐릭터 이름", value=c_name_val)
            ncds = st.text_area("설명", value=c_desc_val, height=100)
            nfs = st.text_area("첫 메시지", value=c_msg_val)
            nsys = st.text_area("시스템 프롬프트", value=c_sys_val, height=150)
            
            if st.button(c_btn_txt, key="btn_save_char"):
                if not ncid: st.error("ID 필수"); st.stop()
                new_data = {"name": ncnm, "description": ncds, "first_message": nfs, "system_prompt": nsys, "lorebooks": []}
                save_json("characters", f"{ncid}.json", new_data)
                st.success(f"저장 완료!"); time.sleep(1); st.rerun()
            
            # [삭제 버튼 추가]
            if mode_char == "기존 캐릭터 수정" and curr_char:
                st.divider()
                if st.button("🗑️ 이 캐릭터 영구 삭제", type="primary", key="del_char_btn"):
                    if delete_json("characters", f"{sel_cid}.json"):
                        st.success("캐릭터 삭제됨. 잘 가요..."); time.sleep(1); st.rerun()
                    else: st.error("삭제 실패")

        # --- 오른쪽: 유저 관리 ---
        with col2:
            st.subheader("👤 유저 페르소나 관리")
            mode_user = st.radio("작업 모드", ["현재 페르소나 수정", "새 페르소나 생성"], key="mode_user", horizontal=True)

            if mode_user == "현재 페르소나 수정" and curr_user:
                u_id_val, u_name_val = sel_uid, curr_user.get('name', '')
                u_gen_val, u_age_val = curr_user.get('gender', ''), curr_user.get('age', '')
                u_prof_val, u_btn_txt, u_id_disable = curr_user.get('profile', ''), "수정사항 저장", True
            else:
                u_id_val, u_name_val, u_gen_val, u_age_val, u_prof_val = "", "", "", "", ""
                u_btn_txt, u_id_disable = "새 페르소나 생성", False

            uid_input = st.text_input("유저 ID", value=u_id_val, disabled=u_id_disable)
            u_name = st.text_input("유저 이름", value=u_name_val)
            u_gender = st.text_input("성별", value=u_gen_val)
            u_age = st.text_input("나이", value=u_age_val)
            u_profile = st.text_area("프로필", value=u_prof_val, height=150)

            if st.button(u_btn_txt, key="btn_save_user"):
                if not uid_input: st.error("ID 필수"); st.stop()
                new_user_data = {"name": u_name, "gender": u_gender, "age": u_age, "profile": u_profile}
                save_json("users", f"{uid_input}.json", new_user_data)
                st.success(f"저장 완료!"); time.sleep(1); st.rerun()

            # [삭제 버튼 추가]
            if mode_user == "현재 페르소나 수정" and curr_user and sel_uid != "default":
                st.divider()
                if st.button("🗑️ 이 페르소나 영구 삭제", type="primary", key="del_user_btn"):
                    if delete_json("users", f"{sel_uid}.json"):
                        st.success("페르소나 삭제됨."); time.sleep(1); st.rerun()

else:
    with tab3:
        st.warning("등록된 캐릭터가 없습니다.")
        ncid = st.text_input("캐릭터 ID")
        ncnm = st.text_input("이름")
        if st.button("생성"): save_json("characters", f"{ncid}.json", {"name":ncnm}); st.rerun()
