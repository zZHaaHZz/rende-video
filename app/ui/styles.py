"""
app/ui/styles.py — Inject CSS styles vào Streamlit app.
"""
import streamlit as st


def inject_styles():
    st.markdown("""
<style>
[data-testid="stSidebar"] { background: #13151c; }
.stButton button { width: 100%; }

/* Tạo thanh cuộn riêng biệt cho cột Kết Quả (cột số 2) */
div[data-testid="stTabContent"] > div > div[data-testid="stHorizontalBlock"] > div:nth-child(2) {
    height: calc(100vh - 120px) !important;
    overflow-y: auto !important;
    padding-right: 15px !important;
}
/* Làm đẹp thanh cuộn */
div[data-testid="stTabContent"] > div > div[data-testid="stHorizontalBlock"] > div:nth-child(2)::-webkit-scrollbar {
    width: 6px;
}
div[data-testid="stTabContent"] > div > div[data-testid="stHorizontalBlock"] > div:nth-child(2)::-webkit-scrollbar-track {
    background: transparent;
}
div[data-testid="stTabContent"] > div > div[data-testid="stHorizontalBlock"] > div:nth-child(2)::-webkit-scrollbar-thumb {
    background-color: #555;
    border-radius: 10px;
}

/* Giảm khoảng trắng thừa cho giao diện kịch bản gọn gàng */
div[data-testid="stExpanderDetails"] {
    padding: 0.6rem 0.8rem 0.8rem 0.8rem !important;
}
div[data-testid="stVerticalBlock"] > div {
    gap: 0.4rem !important;
}
div.element-container {
    margin-bottom: 0.15rem !important;
}
hr {
    margin: 0.6rem 0 !important;
}
</style>
""", unsafe_allow_html=True)
