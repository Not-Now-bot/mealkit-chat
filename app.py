import streamlit as st  
import google.generativeai as genai  
from google.generativeai.types import GenerationConfig, HarmCategory, HarmBlockThreshold  
import json  
import os  
import time  

# ==========================================  
# 0. 초기 설정 및 보안 검사 (가장 중요!)
# ==========================================  
st.set_page_config(page_title="Secret Chat", layout="wide")

# [보안 1] 비밀번호 확인 기능
def check_password():
    """Returns `True` if the user had the correct password."""
    # Secrets에 설정된 비번이 없으면 그냥 통과 (보안 취약 알림)
    if "PASSWORD" not in st.secrets["general"]:
        st.error("⚠️ Streamlit Secrets에 'PASSWORD'가 설정되지 않았습니다.")
        return False

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == st.secrets["general"]["PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # 비번 흔적 지우기
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # 처음 접속 시 비번 입력창 띄움
        st.text_input(
            "🔒 접속 비밀번호를 입력하세요", type="password", on_change=password_entered, key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        # 비번 틀렸을 때
        st.text_input(
            "🔒 접속 비밀번호를 입력하세요", type="password", on_change=password_entered, key="password"
        )
        st.error("❌ 비밀번호가 틀렸습니다.")
        return False
    else:
        # 비번 맞음
        return True

# 비밀번호 통과 못하면 여기서 코드 멈춤 (아무것도 안 보여줌)
if not check_password():
    st.stop()

# ==========================================  
# [보안 2] API 키 로드 (Secrets에서 가져오기)
# ==========================================  
try:
    # Streamlit Secrets에서 가져오기
    api_key = st.secrets["general"]["GOOGLE_API_KEY"]
    genai.configure(api_key=api_key)
except Exception as e:
    st.error("🚨 API 키 설정 오류! Streamlit Secrets에 'GOOGLE_API_KEY'를 설정해주세요.")
    st.stop()

# ==========================================  
# 여기서부터는 기존 로직과 동일
# ==========================================  
FOLDERS = ["characters", "users", "history", "memory", "usernotes"]   
for folder in FOLDERS:  
    if not os.path.exists(folder): os.makedirs(folder)  
  
CONFIG_FILE = "config.json"  
  
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
  
MEMORY_LEVELS = {  
    "Lite (5,000자)": 5000,   
    "Standard (10,000자)": 10000,   
    "Heavy (50,000자)": 50000,   
    "Full Archive (100,000자)": 100000  
}  
  
def load_config():  
    curr = DEFAULT_CONFIG.copy()  
    try:  
        if os.path.exists(CONFIG_FILE):  
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:  
                saved = json.load(f)  
                curr.update(saved)  
    except: pass  
    return curr  
  
def update_config(key, value):  
    curr = load_config()  
    curr[key] = value  
    with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(curr, f, indent=4)  
  
def save_advanced_config(chat_model, memory_model, memory_level, temp, top_p, max_tok):  
    curr = load_config()  
    curr.update({  
        "chat_model": chat_model,   
        "memory_model": memory_model,   
        "memory_level": memory_level,  
        "temperature": temp,  
        "top_p": top_p,  
        "max_tokens": max_tok  
    })  
    with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(curr, f, indent=4)  
  
# ==========================================  
# 1. 데이터 핸들링  
# ==========================================  
PROMPT_TEMPLATES = {  
    "기본 (Default)": "",  
    "1:1 깊은 대화": "[Mode: Deep Chat]\nFocus on emotional connection.",  
    "소설/시뮬레이션": "[Mode: Novel]\nNarrate vividly. Control NPCs.",  
    "가혹한 상황": "[Mode: Survival]\nBe cynical and realistic."  
}  
SUMMARY_RULES = "Summarize events, emotions, and vows."  
  
def load_json(folder, filename):  
    try:  
        with open(os.path.join(folder, filename), "r", encoding="utf-8") as f: return json.load(f)  
    except: return {}  
  
def save_json(folder, filename, data):  
    with open(os.path.join(folder, filename), "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)  
  
def delete_file(folder, filename):  
    p = os.path.join(folder, filename)  
    if os.path.exists(p): os.remove(p)  
  
def load_user_note(char_id): return load_json("usernotes", f"{char_id}.json").get("content", "")  
def save_user_note(char_id, content): save_json("usernotes", f"{char_id}.json", {"content": content})  
  
def load_characters():  
    db = {}  
    if not os.path.exists("characters"): return db  
    for f in os.listdir("characters"):  
        if f.endswith(".json"):  
            data = load_json("characters", f)  
            cid = f.replace(".json", "")  
            for k in ["name","description","system_prompt","first_message","image"]: data.setdefault(k,"")  
            data.setdefault("lorebooks", [])  
            img_p = os.path.join("characters", data["image"]) if data["image"] else os.path.join("characters", "default.jpg")  
            data["image_path"] = img_p if os.path.exists(img_p) else None  
            db[cid] = data  
    return db  
  
def load_users():  
    db = {}  
    if not os.path.exists("users"): return db  
    for f in os.listdir("users"):  
        if f.endswith(".json"):   
            data = load_json("users", f)  
            data.setdefault("image", "")  
            img_p = os.path.join("users", data["image"]) if data["image"] else None  
            data["image_path"] = img_p if img_p and os.path.exists(img_p) else None  
            db[f.replace(".json", "")] = data  
              
    if not db:  
        def_u = {"name": "User", "gender": "Unknown", "age": "Unknown", "profile": "Traveler"}  
        save_json("users", "default.json", def_u); db["default"] = def_u  
    return db  
  
def load_memory(char_id):  
    mem = load_json("memory", f"{char_id}.json")  
    if not mem: return {"summary": "기록 없음", "recent_event": "", "location": "알 수 없음", "relations": ""}  
    return mem  
  
def trigger_lorebooks(text, lorebooks):  
    act = []  
    text = text.lower()  
    for b in lorebooks:  
        tags = [t.strip().lower() for t in b.get("tags", "").split(",") if t.strip()]  
        for tag in tags:  
            if tag in text: act.append(b.get("content", "")); break  
    return "\n[Active Lorebook]\n" + "\n".join(act[:5]) + "\n" if act else ""  
  
def generate_export_text(cname, uname, msgs):  
    return "\n".join([f"{cname if m['role']=='assistant' else uname}:\n{m['content']}\n" for m in msgs])  
  
def get_safety_settings():  
    return {  
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,  
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,  
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,  
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,  
    }  
  
def generate_response(chat_model_id, prompt_temp, c_char, c_user, mem, lore, history, user_note, temperature, top_p, max_tokens):  
    chat_model = genai.GenerativeModel(chat_model_id)  
      
    gen_config = GenerationConfig(  
        temperature=temperature,  
        top_p=top_p,  
        max_output_tokens=max_tokens  
    )  
      
    safety = get_safety_settings()  
  
    recent = history[-1]['content'] if history and history[-1]['role'] == 'user' else ""  
    ctx = "\n".join([m['content'] for m in history[-5:]])  
    active_lore = trigger_lorebooks(ctx + recent, c_char.get("lorebooks", []))  
      
    sys = f"""{prompt_temp}  
    [Target] {c_char['name']}: {c_char['description']}  
    [System] {c_char['system_prompt']}  
    [User] {c_user['name']} / {c_user.get('gender')} / {c_user.get('age')} / {c_user.get('profile')}  
    [User Note] {user_note}  
    [Memory] {mem.get('summary')} / {mem.get('location')} / {mem.get('relations')}  
    {mem.get('recent_event')}  
    {active_lore}"""  
      
    full = f"System: {sys}\n" + "\n".join([f"{m['role']}: {m['content']}" for m in history])  
      
    return chat_model.generate_content(full, generation_config=gen_config, safety_settings=safety).text  
  
CHARACTER_DB = load_characters()  
USER_DB = load_users()  
current_config = load_config()  
  
# ==========================================  
# 2. 사이드바  
# ==========================================  
with st.sidebar:  
    st.title("🎛️ AI 엔진 설정")
    # API 키 수동 입력창 제거됨 (Secrets 사용)
    st.success("🔒 보안 연결됨")
    
    try:  
        av_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]  
        av_models.sort()  
    except: av_models = ["models/gemini-1.5-flash", "models/gemini-pro"]  
      
    try: ic = av_models.index(current_config.get("chat_model"))  
    except: ic = 0  
    try: im = av_models.index(current_config.get("memory_model"))  
    except: im = 0  
  
    chat_model_id = st.selectbox("💬 대화 모델", av_models, index=ic)  
    memory_model_id = st.selectbox("🧠 기억 모델", av_models, index=im)  
      
    with st.expander("🛠️ 대화 파라미터 (고급)", expanded=False):  
        st.markdown("**Temperature (창의성/온도)**")  
        st.caption("높을수록 창의적이고 예측불가")  
        sel_temp = st.slider("Temp", 0.0, 2.0, float(current_config.get("temperature", 1.0)), 0.1, label_visibility="collapsed")  
          
        st.markdown("**Top P (단어 다양성)**")  
        st.caption("높을수록 다양한 어휘 사용")  
        sel_topp = st.slider("TopP", 0.0, 1.0, float(current_config.get("top_p", 0.95)), 0.05, label_visibility="collapsed")  
          
        st.markdown("**Max Tokens (답변 길이/추론 강도)**")  
        st.caption("한 번에 대답할 수 있는 최대 길이")  
        sel_tok = st.slider("Tokens", 100, 8192, int(current_config.get("max_tokens", 8192)), 100, label_visibility="collapsed")  
  
    if (chat_model_id != current_config.get("chat_model")) or \
       (memory_model_id != current_config.get("memory_model")) or \
       (sel_temp != current_config.get("temperature")) or \
       (sel_topp != current_config.get("top_p")) or \
       (sel_tok != current_config.get("max_tokens")):  
          
        save_advanced_config(chat_model_id, memory_model_id, current_config.get("memory_level"), sel_temp, sel_topp, sel_tok)  
        st.session_state["config_updated"] = True  
        st.rerun()  
          
    st.divider()  
      
    # ----------------------------------------------------  
    st.subheader("🎭 출연진 (Cast)")  
      
    # 1. 페르소나 (User)  
    user_options = list(USER_DB.keys())  
    saved_uid = current_config.get("last_user_id", "")  
    try: default_uid_idx = user_options.index(saved_uid)  
    except: default_uid_idx = 0  
      
    sel_uid = st.selectbox("👤 페르소나", user_options, index=default_uid_idx,format_func=lambda x: USER_DB[x]['name'])  
      
    if sel_uid != saved_uid:  
        update_config("last_user_id", sel_uid)  
        st.rerun()  
  
    curr_user = USER_DB[sel_uid]  
    if curr_user.get("image_path"):   
        st.image(curr_user["image_path"], caption=curr_user["name"], use_container_width=True)  
    else:   
        st.info("이미지 없음 (페르소나)")  
          
    st.markdown("---")  
  
    # 2. 캐릭터 (AI)  
    if CHARACTER_DB:  
        char_options = list(CHARACTER_DB.keys())  
        saved_cid = current_config.get("last_char_id", "")  
        try: default_cid_idx = char_options.index(saved_cid)  
        except: default_cid_idx = 0  
  
        sel_cid = st.selectbox("🤖 캐릭터", char_options, index=default_cid_idx, format_func=lambda x: CHARACTER_DB[x]["name"])  
          
        if sel_cid != saved_cid:  
            update_config("last_char_id", sel_cid)  
            st.rerun()  
  
        if "last_cid" not in st.session_state: st.session_state.last_cid = sel_cid  
        if st.session_state.last_cid != sel_cid:  
            st.session_state.tmp_lbs = CHARACTER_DB[sel_cid].get("lorebooks", [])  
            st.session_state.last_cid = sel_cid  
            st.rerun()  
          
        curr_char = CHARACTER_DB[sel_cid]  
          
        if curr_char.get("image_path"):   
            st.image(curr_char["image_path"], caption=curr_char["name"], use_container_width=True)  
        else:  
            st.info("이미지 없음 (캐릭터)")  
    else:  
        st.error("캐릭터 없음"); st.stop()  
  
    with st.expander(f"✏️ 페르소나 설정"):  
        u_img_up = st.file_uploader("프사 변경", type=["png","jpg"], key=f"u_img_up_{sel_uid}")  
        curr_u_img_val = curr_user.get("image", "")  
  
        if u_img_up and (u_img_up.name != curr_u_img_val):  
            with open(os.path.join("users", u_img_up.name), "wb") as f: f.write(u_img_up.getbuffer())  
            user_data = load_json("users", f"{sel_uid}.json")  
            user_data["image"] = u_img_up.name  
            save_json("users", f"{sel_uid}.json", user_data)  
            st.success("프로필 변경!")   
            time.sleep(0.5)  
            st.rerun()  
  
        with st.form("edit_user_form"):  
            un = st.text_input("이름", curr_user['name'])  
            ug = st.text_input("성별", curr_user.get('gender', ''))  
            ua = st.text_input("나이/외관", curr_user.get('age', ''))  
            up = st.text_area("프로필", curr_user.get('profile', ''), height=100)  
            if st.form_submit_button("정보 저장"):  
                new_data = load_json("users", f"{sel_uid}.json")  
                new_data.update({"name":un, "gender":ug, "age":ua, "profile":up})  
                save_json("users", f"{sel_uid}.json", new_data)  
                st.rerun()  
  
    with st.expander("➕ 페르소나 추가"):  
        nid = st.text_input("ID", key="n_uid"); nnm = st.text_input("이름", key="n_unm")  
        if st.button("생성"):   
            if nid and nid not in USER_DB: save_json("users", f"{nid}.json", {"name": nnm}); st.rerun()  
      
    st.divider()  
  
    with st.expander("🤖 캐릭터 관리"):  
        curr_char = CHARACTER_DB[sel_cid]  
        ncid = st.text_input("새ID", key="ncid"); ncnm = st.text_input("새이름", key="ncnm")  
        if st.button("생성", key="btn_c_new"):   
            if ncid and ncid not in CHARACTER_DB: save_json("characters", f"{ncid}.json", {"name":ncnm}); st.rerun()  
        if st.button("삭제", key="btn_c_del"): delete_file("characters", f"{sel_cid}.json"); st.rerun()  
        if st.button("대화 초기화"):   
            save_json("history", f"{sel_cid}.json", [])  
            save_json("memory", f"{sel_cid}.json", {"summary":"", "recent_event":""})  
            save_user_note(sel_cid, "")  
            st.rerun()  
  
# ==========================================  
# 3. 메인 로직  
# ==========================================  
tab1, tab2, tab3 = st.tabs(["💬 대화", "🧠 기억", "✏️ 스튜디오"])  
sess_key = f"hist_{sel_cid}"  
if sess_key not in st.session_state: st.session_state[sess_key] = load_json("history", f"{sel_cid}.json") or []  
mem_data = load_memory(sel_cid)  
u_note = load_user_note(sel_cid)  
  
with tab1:  
    c1, c2 = st.columns([4,1])  
    with c1:  
        with st.expander("📝 유저 노트", expanded=False):  
            note_in = st.text_area("내용", value=u_note, height=80, key=f"unote_{sel_cid}")  
            if st.button("노트 저장"): save_user_note(sel_cid, note_in); st.rerun()  
    with c2:  
        st.download_button("💾 대화 저장", generate_export_text(curr_char['name'], curr_user['name'], st.session_state[sess_key]), f"{sel_cid}.txt")  
  
    if not st.session_state[sess_key] and curr_char.get("first_message"):  
        st.session_state[sess_key].append({"role": "assistant", "content": curr_char["first_message"]})  
        save_json("history", f"{sel_cid}.json", st.session_state[sess_key])  
  
    for i, m in enumerate(st.session_state[sess_key]):  
        # [NEW] 메시지 역할(role)에 따라 프로필 이미지 결정  
        if m["role"] == "user":  
            avatar_img = curr_user.get("image_path") # 유저 이미지 or None  
        else:  
            avatar_img = curr_char.get("image_path") # 캐릭터 이미지 or None  
  
        # [NEW] avatar 파라미터에 이미지 전달 (없으면 None -> 기본 아이콘)  
        with st.chat_message(m["role"], avatar=avatar_img):  
            st.markdown(m["content"].replace("\n", "  \n"))  
            with st.expander("수정"):  
                ed = st.text_area("내용", m["content"], key=f"ed_{sel_cid}_{i}")  
                if st.button("저장", key=f"sv_{sel_cid}_{i}"):   
                    st.session_state[sess_key][i]["content"] = ed; save_json("history", f"{sel_cid}.json", st.session_state[sess_key]); st.rerun()  
                if st.button("삭제", key=f"dl_{sel_cid}_{i}"):   
                   del st.session_state[sess_key][i]; save_json("history", f"{sel_cid}.json", st.session_state[sess_key]); st.rerun()  
                if (i==len(st.session_state[sess_key])-1) and m['role']=='assistant':  
                   if st.button("재생성", key=f"rg_{sel_cid}_{i}"):  
                       del st.session_state[sess_key][i]  
                       with st.spinner("..."):  
                           try:  
                               nr = generate_response(chat_model_id, "", curr_char, curr_user, mem_data, curr_char["lorebooks"], st.session_state[sess_key], u_note, sel_temp, sel_topp, sel_tok)  
                               st.session_state[sess_key].append({"role":"assistant","content":nr})  
                               save_json("history", f"{sel_cid}.json", st.session_state[sess_key]); st.rerun()  
                           except Exception as e: st.error(f"생성 실패: {e}")  
  
    if p := st.chat_input("입력..."):  
        st.session_state[sess_key].append({"role":"user", "content":p})  
        save_json("history", f"{sel_cid}.json", st.session_state[sess_key])  
        try:  
            r = generate_response(chat_model_id, "", curr_char, curr_user, mem_data, curr_char["lorebooks"], st.session_state[sess_key], u_note, sel_temp, sel_topp, sel_tok)  
            st.session_state[sess_key].append({"role":"assistant", "content":r})  
            save_json("history", f"{sel_cid}.json", st.session_state[sess_key]); st.rerun()  
        except Exception as e: st.error(f"Error: {e}")  
  
with tab2:  
    cur_sum = len(mem_data.get('summary', ''))  
    cur_rec = len(mem_data.get('recent_event', ''))  
    cur_total = cur_sum + cur_rec  
      
    st.header("🧠 장기 기억 제어실")  
      
    c1, c2 = st.columns(2)  
    with c1:  
        st.subheader("📊 상태")  
          
        saved_level_name = current_config.get("memory_level", "Standard (10,000자)")  
        mem_keys = list(MEMORY_LEVELS.keys())  
        try: init_idx = mem_keys.index(saved_level_name)  
        except: init_idx = 1  
          
        sel_mem_level_name = st.selectbox("목표 용량 설정", mem_keys, index=init_idx)  
          
        if sel_mem_level_name != saved_level_name:  
            save_advanced_config(chat_model_id, memory_model_id, sel_mem_level_name, sel_temp, sel_topp, sel_tok)  
            st.rerun()  
  
        target_limit = MEMORY_LEVELS[sel_mem_level_name]  
          
        cols_metric = st.columns(2)  
        cols_metric[0].metric("현재 기억량", f"{cur_total:,} 자")  
        cols_metric[1].metric("목표 제한", f"{target_limit:,} 자")  
          
        progress_val = min(cur_total / target_limit, 1.0)  
        st.progress(progress_val, text=f"사용량: {int(progress_val*100)}%")  
          
        st.divider()  
        st.text_area("Summary (요약본)", mem_data.get('summary'), height=150, disabled=True)  
        if st.button("🔄 기억 업데이트 (압축 실행)", type="primary"):  
            with st.spinner("기억을 정리하는 중..."):  
                try:  
                    m = genai.GenerativeModel(memory_model_id)  
                    log = "".join([f"{x['role']}:{x['content']}\n" for x in st.session_state[sess_key]])  
                    p = f"""  
                    You are a memory manager. Summarize the following story.  
                    Target length: approx {target_limit} chars.  
                    {SUMMARY_RULES}  
                    Old Summary: {mem_data.get('summary')}  
                    Location: {mem_data.get('location')}  
                    Recent Log: {log}  
                    Return ONLY a JSON object: {{"summary": "...", "recent_event": "...", "location": "...", "relations": "..."}}  
                    """  
                    res = m.generate_content(p).text.replace("```json","").replace("```","").strip()  
                    save_json("memory", f"{sel_cid}.json", json.loads(res)); st.success("업데이트 완료!"); time.sleep(1); st.rerun()  
                except Exception as e: st.error(f"실패: {e}")  
  
    with c2:  
        st.subheader("✍️ 수동 편집")  
        with st.form("mem_edit"):  
            fs = st.text_area("Summary (가장 중요한 기억)", mem_data.get('summary'), height=200)  
            fr = st.text_area("Recent (최근 사건)", mem_data.get('recent_event'))  
            fl = st.text_input("Location (현재 위치)", mem_data.get('location'))  
            fre = st.text_area("Relations (관계도)", mem_data.get('relations'))  
            if st.form_submit_button("저장"):  
                save_json("memory", f"{sel_cid}.json", {"summary":fs,"recent_event":fr,"location":fl,"relations":fre}); st.success("수정 완료"); time.sleep(0.5); st.rerun()  
  
with tab3:  
    st.header(f"✏️ {curr_char['name']}")  
    if "tmp_lbs" not in st.session_state: st.session_state.tmp_lbs = curr_char.get("lorebooks", [])  
  
    def save_char_data():  
        nm = st.session_state.get(f"n_nm_{sel_cid}", curr_char['name'])  
        ds = st.session_state.get(f"n_ds_{sel_cid}", curr_char['description'])  
        im = st.session_state.get(f"n_im_{sel_cid}", curr_char.get('image',''))  
        fst = st.session_state.get(f"n_fst_{sel_cid}", curr_char['first_message'])  
        sys = st.session_state.get(f"n_sys_{sel_cid}", curr_char['system_prompt'])  
        lbs = st.session_state.tmp_lbs   
        save_json("characters", f"{sel_cid}.json", {  
            "name": nm, "description": ds, "image": im,   
            "system_prompt": sys, "first_message": fst, "lorebooks": lbs  
        })  
        st.success("저장 완료!"); time.sleep(1); st.rerun()  
  
    if st.button("💾 상단 저장", key=f"save_top_{sel_cid}"): save_char_data()  
  
    t3_1, t3_2 = st.tabs(["정보", "로어북"])  
    with t3_1:  
        c1, c2 = st.columns(2)  
        with c1:  
            st.text_input("이름", value=curr_char['name'], key=f"n_nm_{sel_cid}")  
            st.text_input("소개", value=curr_char['description'], key=f"n_ds_{sel_cid}")  
              
            img_up = st.file_uploader("이미지 업로드", type=["png","jpg"], key=f"up_{sel_cid}")  
            current_img_val = st.session_state.get(f"n_im_{sel_cid}", curr_char.get('image',''))  
              
            if img_up and (img_up.name != current_img_val):  
                with open(os.path.join("characters", img_up.name), "wb") as f: f.write(img_up.getbuffer())  
                st.session_state[f"n_im_{sel_cid}"] = img_up.name  
                st.success("이미지 저장 완료!")  
                time.sleep(1)  
                st.rerun()  
                  
            st.text_input("이미지 파일명", value=curr_char.get('image',''), key=f"n_im_{sel_cid}")  
  
        with c2:  
            st.text_area("첫 대사", value=curr_char['first_message'], height=150, key=f"n_fst_{sel_cid}")  
        st.text_area("시스템 프롬프트", value=curr_char['system_prompt'], height=200, key=f"n_sys_{sel_cid}")  
  
    with t3_2:  
        if st.button("➕ 로어북 추가", key=f"lb_add_{sel_cid}"):   
            st.session_state.tmp_lbs.append({"title":"New","tags":"","content":""}); st.rerun()  
        save_lb = []  
        del_idx = []  
        for i, b in enumerate(st.session_state.tmp_lbs):  
             with st.expander(f"#{i+1} {b.get('title')}", expanded=False):  
                bt = st.text_input("제목", b.get('title'), key=f"lb_t_{sel_cid}_{i}")  
                bg = st.text_input("태그", b.get('tags'), key=f"lb_g_{sel_cid}_{i}")  
                bc = st.text_area("내용", b.get('content'), key=f"lb_c_{sel_cid}_{i}")  
                if st.button("삭제", key=f"lb_d_{sel_cid}_{i}"): del_idx.append(i)  
                save_lb.append({"title":bt, "tags":bg, "content":bc})  
        if del_idx:  
            for i in sorted(del_idx, reverse=True): del st.session_state.tmp_lbs[i]  
            st.rerun()  
        else: st.session_state.tmp_lbs = save_lb  
  
    st.divider()  
    if st.button("💾 하단 저장", key=f"save_bot_{sel_cid}"): save_char_data()
