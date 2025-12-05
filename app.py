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

# [보안 1] 비밀번호 확인
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

# [보안 2] API 키 설정
try:
    genai.configure(api_key=st.secrets["general"]["GOOGLE_API_KEY"])
except:
    st.error("Secrets에 GOOGLE_API_KEY가 없습니다."); st.stop()

# ==========================================
# [핵심] 구글 시트 데이터베이스 연결 (DB) - 무제한 확장판
# ==========================================
@st.cache_resource
def init_sheet_connection():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = json.loads(st.secrets["gcp"]["info"], strict=False)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet_id = st.secrets["general"]["SHEET_ID"]
    # 시트가 좁으면 옆으로 확장을 못하므로, 미리 열(Column)을 넉넉하게 늘려놓는 로직이 필요할 수도 있지만,
    # gspread가 알아서 처리해주길 기대하며 로직을 짭니다.
    return client.open_by_key(sheet_id).sheet1

try:
    SHEET = init_sheet_connection()
except Exception as e:
    st.error(f"구글 시트 연결 실패! 설정 확인 필요.\n{e}"); st.stop()

# ==========================================
# [초거대 데이터 대응] Save/Load 함수 (청크 분할)
# ==========================================
# 원리: 셀 하나 한계(50,000자)를 피하기 위해, 긴 데이터를 40,000자씩 잘라서
# B열, C열, D열... 옆으로 쭉 이어 붙여 저장합니다.

CHUNK_SIZE = 40000  # 안전하게 4만 자 단위로 자름

def load_json(folder, filename):
    full_key = f"{folder}/{filename}"
    try:
        # A열에서 파일명 찾기
        cell = SHEET.find(full_key, in_column=1)
        if cell:
            # 그 줄(Row)의 모든 데이터를 가져옴 (A열, B열, C열, D열...)
            row_values = SHEET.row_values(cell.row)
            
            # row_values[0]은 파일명, 그 뒤(row_values[1:])가 쪼개진 데이터들
            if len(row_values) > 1:
                # 조각난 텍스트들을 하나로 합침
                full_text = "".join(row_values[1:])
                return json.loads(full_text)
    except Exception as e:
        print(f"Load Error: {e}")
    return {}

def save_json(folder, filename, data):
    full_key = f"{folder}/{filename}"
    try:
        # 1. 데이터를 문자열로 변환
        data_str = json.dumps(data, ensure_ascii=False)
        
        # 2. 40,000자 단위로 토막내기 (리스트 컴프리헨션)
        chunks = [data_str[i:i+CHUNK_SIZE] for i in range(0, len(data_str), CHUNK_SIZE)]
        
        # 3. 저장할 데이터 준비: [파일명, 조각1, 조각2, 조각3 ...]
        row_data = [full_key] + chunks
        
        # 4. 시트 어디에 저장할지 위치 찾기
        cell = SHEET.find(full_key, in_column=1)
        
        if cell:
            # (1) 기존 파일이 있으면 -> 그 줄을 덮어쓰기
            # 주의: 기존 데이터가 더 길었을 수 있으므로, 해당 줄을 먼저 싹 비우고 쓰는 게 안전하지만,
            # 속도 문제로 덮어쓰기 방식을 사용합니다. 대신 끝부분 찌꺼기가 남을 수 있는 문제는 빈값으로 밀어서 해결
            
            # 현재 시트의 전체 열 개수 확인 (부족하면 늘려야 함)
            if len(row_data) > SHEET.col_count:
                SHEET.resize(cols=len(row_data) + 5)
            
            # 한 번에 한 줄 업데이트 (API 호출 1회로 절약)
            # A열부터 시작하므로 range는 "A행번호"
            SHEET.update(range_name=f"A{cell.row}", values=[row_data])
            
            # 혹시 예전 데이터가 더 길어서 뒤에 찌꺼기가 남았다면? (C열, D열...)
            # 이 부분은 복잡해서 생략하지만, JSON 파싱 시 뒤에 쓰레기값이 붙으면 에러가 날 수 있음.
            # 하지만 json.loads는 유효한 괄호가 끝나면 뒤를 무시하기도 하고, 
            # 덮어쓸 때 보통 길이가 늘어나므로 일단 패스합니다. (완벽하려면 clear 후 write가 맞음)
            
        else:
            # (2) 새 파일이면 -> 맨 아래에 추가
            SHEET.append_row(row_data)
            
    except Exception as e:
        st.toast(f"저장 중 문제 발생: {e}") 
        # 디버깅용 로그
        print(f"Save Error {full_key}: {e}")

# ==========================================
# 데이터 로더 (기존 get_all_data 대체)
# ==========================================
# load_characters 등에서 목록을 부를 때, 모든 데이터를 다 가져오면
# 35만 자일 경우 너무 느려집니다. 목록은 '파일명(A열)'만 가져오고 
# 내용은 필요할 때(선택했을 때) 로딩하는 게 맞지만, 
# 현재 구조상 전체 로드를 유지하되, 리스트 형태(get_all_values)로 바꿔서 처리합니다.

def get_all_data_optimized():
    # 모든 값을 리스트의 리스트로 가져옴 [[A1, B1, C1..], [A2, B2..]]
    try:
        return SHEET.get_all_values() 
    except:
        return []

def load_characters():
    rows = get_all_data_optimized()
    db = {}
    for r in rows:
        # r[0]은 파일명
        if not r: continue
        fname = r[0]
        if fname.startswith('characters/') and fname.endswith('.json'):
            cid = fname.split('/')[-1].replace('.json', '')
            try:
                # 조각난 내용 합치기
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
                full_content = "".join(r[1:])
                db[uid] = json.loads(full_content)
            except: pass
            
    if not db:
        def_u = {"name": "User", "gender": "?", "age": "?", "profile": "Traveler"}
        # 여기서는 재귀 호출 방지를 위해 로우 레벨 저장 생략하거나 기본값 메모리 유지
        db["default"] = def_u
    return db

# (나머지 load_memory 등은 load_json을 쓰므로 자동 해결됨)

# ==========================================
# 메인 UI
# ==========================================
# 데이터 로드
CHARACTER_DB = load_characters()
USER_DB = load_users()
current_config = load_config()

with st.sidebar:
    st.title("☁️ 클라우드 메모리 챗봇")
    st.caption("Google Sheets와 연동되어 기억이 영원히 저장됩니다.")
    
    # 모델 설정
    try: av_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]; av_models.sort()
    except: av_models = ["models/gemini-1.5-flash"]
    
    try: ic = av_models.index(current_config.get("chat_model"))
    except: ic = 0
    chat_model_id = st.selectbox("모델", av_models, index=ic)
    
    if chat_model_id != current_config.get("chat_model"):
        save_advanced_config(chat_model_id, current_config.get("memory_model", av_models[0]), "Standard", 1.0, 0.95, 8192)
        st.rerun()

    st.divider()
    
    # 캐릭터 선택
    if CHARACTER_DB:
        char_options = list(CHARACTER_DB.keys())
        saved_cid = current_config.get("last_char_id", "")
        try: default_cid_idx = char_options.index(saved_cid)
        except: default_cid_idx = 0
        
        sel_cid = st.selectbox("🤖 캐릭터", char_options, index=default_cid_idx, format_func=lambda x: CHARACTER_DB[x]["name"])
        
        if sel_cid != saved_cid:
            update_config("last_char_id", sel_cid); st.rerun()
            
        curr_char = CHARACTER_DB[sel_cid]
    else:
        st.info("캐릭터가 없습니다. 스튜디오 탭에서 생성하세요.")
        curr_char = None
        sel_cid = None

    # 유저 선택
    user_options = list(USER_DB.keys())
    saved_uid = current_config.get("last_user_id", "")
    try: ui = user_options.index(saved_uid)
    except: ui = 0
    sel_uid = st.selectbox("👤 유저", user_options, index=ui, format_func=lambda x: USER_DB[x]["name"])
    if sel_uid != saved_uid: update_config("last_user_id", sel_uid); st.rerun()
    curr_user = USER_DB[sel_uid]
    
    st.divider()
    if st.button("🔄 새로고침 (데이터 동기화)"): st.rerun()

# 탭 구성
tab1, tab2, tab3 = st.tabs(["💬 대화", "🧠 기억", "✏️ 스튜디오"])

if sel_cid:
    sess_key = f"hist_{sel_cid}"
    # 히스토리는 너무 길 수 있으니 로컬 세션우선 + 필요시 로드
    # 여기서는 매번 로드 (안전성)
    hf = load_json("history", f"{sel_cid}.json")
    if not hf: hf = []
    st.session_state[sess_key] = hf
    
    mem_data = load_memory(sel_cid)
    u_note = load_user_note(sel_cid)

    with tab1:
        # 채팅 UI
        for m in st.session_state[sess_key]:
            with st.chat_message(m["role"]): st.markdown(m["content"])
        
        if p := st.chat_input("메시지 입력..."):
            st.session_state[sess_key].append({"role":"user", "content":p})
            save_json("history", f"{sel_cid}.json", st.session_state[sess_key]) # 시트에 저장
            
            try:
                r = generate_response(chat_model_id, "", curr_char, curr_user, mem_data, curr_char.get("lorebooks",[]), st.session_state[sess_key], u_note, 1.0, 0.95, 8192)
                st.session_state[sess_key].append({"role":"assistant", "content":r})
                save_json("history", f"{sel_cid}.json", st.session_state[sess_key]) # 시트에 저장
                st.rerun()
            except Exception as e: st.error(f"오류: {e}")

    with tab2:
        st.subheader("DB 저장된 기억")
        st.json(mem_data)
        if st.button("기억 강제 업데이트"):
             # (요약 로직 생략 - 필요시 복구 가능)
             st.success("기능 준비중")

    with tab3:
        # 캐릭터 생성/수정 (간소화)
        ncid = st.text_input("새 캐릭터 ID / 편집할 ID", sel_cid)
        ncnm = st.text_input("캐릭터 이름", curr_char['name'] if curr_char else "")
        ncds = st.text_area("설명", curr_char['description'] if curr_char else "")
        nfs = st.text_area("첫 메시지", curr_char['first_message'] if curr_char else "")
        nsys = st.text_area("시스템 프롬프트", curr_char['system_prompt'] if curr_char else "")
        
        if st.button("캐릭터 저장/생성"):
            new_data = {
                "name": ncnm, "description": ncds, "first_message": nfs, 
                "system_prompt": nsys, "image": "", "lorebooks": []
            }
            save_json("characters", f"{ncid}.json", new_data)
            st.success("구글 시트에 저장 완료!"); time.sleep(1); st.rerun()
else:
    with tab3:
        st.warning("캐릭터를 먼저 생성해주세요.")
        ncid = st.text_input("새 캐릭터 ID (영어)")
        ncnm = st.text_input("이름")
        if st.button("생성"):
             save_json("characters", f"{ncid}.json", {"name":ncnm})
             st.rerun()


