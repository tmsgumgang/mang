import streamlit as st
import pandas as pd
import re

# =========================================================
# [Math] 계산 로직 (여기에 독립적으로 정의)
# =========================================================
def calculate_linearity(standards, measurements):
    """ 선형회귀분석: R^2, 기울기, 절편 계산 """
    try:
        n = len(standards)
        if n != len(measurements) or n < 2: return None, "데이터 개수 불일치"

        sum_x = sum(standards)
        sum_y = sum(measurements)
        sum_xy = sum(x*y for x, y in zip(standards, measurements))
        sum_xx = sum(x*x for x in standards)

        # 기울기(m)와 절편(b)
        denominator = (n * sum_xx - sum_x**2)
        if denominator == 0: return None, "분모가 0입니다 (x값 동일)"
        
        m = (n * sum_xy - sum_x * sum_y) / denominator
        b = (sum_y - m * sum_x) / n

        # R^2 계산
        y_mean = sum_y / n
        ss_tot = sum((y - y_mean)**2 for y in measurements)
        ss_res = sum((y - (m*x + b))**2 for x, y in zip(standards, measurements))
        
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        
        return {
            "R2": r_squared,
            "slope": m,
            "intercept": b,
            "equation": f"y = {m:.4f}x + {b:.4f}"
        }, None
    except Exception as e: return None, str(e)

def calculate_precision_accuracy(true_val, measured_vals):
    """ 정확도(오차율) 및 정밀도(RSD) 계산 """
    try:
        n = len(measured_vals)
        if n < 1: return None
        avg = sum(measured_vals) / n
        
        # 정확도 (%)
        accuracy_error = abs((avg - true_val) / true_val) * 100 if true_val != 0 else 0
        
        # 정밀도 (RSD %)
        if n > 1:
            variance = sum((x - avg)**2 for x in measured_vals) / (n - 1)
            std_dev = variance ** 0.5
            rsd = (std_dev / avg) * 100 if avg != 0 else 0
        else: rsd = 0.0

        return {"average": avg, "accuracy_error": accuracy_error, "rsd": rsd}
    except: return None

# =========================================================
# [UI] 정도검사 화면 출력 함수
# =========================================================
def show_qc_ui():
    st.markdown("""<style>
        .pass-box { background-color: #dcfce7; border: 2px solid #22c55e; padding: 15px; border-radius: 10px; text-align: center; color: #166534; font-weight: bold; font-size: 1.2rem; margin-top: 10px; }
        .fail-box { background-color: #fee2e2; border: 2px solid #ef4444; padding: 15px; border-radius: 10px; text-align: center; color: #991b1b; font-weight: bold; font-size: 1.2rem; margin-top: 10px; }
    </style>""", unsafe_allow_html=True)

    st.header("⚖️ 정도검사 자동 계산기")
    st.caption("측정 데이터를 입력하면 직선성(R²), 정확도, 반복성을 자동 판정합니다.")
    st.divider()

    qc_col1, qc_col2 = st.columns([1, 1.5])
    
    with qc_col1:
        st.subheader("1. 설정")
        qc_type = st.radio("검사 종류", ["직선성 (R²)", "정확도/반복성"], horizontal=True)
        target_item = st.selectbox("측정 항목", ["TOC", "TN", "TP", "SS", "pH", "COD", "기타"])
        
        st.markdown("---")
        st.markdown("**🔍 합격 기준 설정**")
        if qc_type == "직선성 (R²)":
            criteria = st.number_input("R² 기준 (이상)", value=0.98, step=0.01, format="%.3f")
        else:
            crit_acc = st.number_input("정확도 오차율 (% 이하)", value=10.0, step=0.5)
            crit_rsd = st.number_input("반복성 RSD (% 이하)", value=5.0, step=0.5)

    with qc_col2:
        st.subheader("2. 데이터 입력 & 결과")
        
        # [A] 직선성 검사 로직
        if qc_type == "직선성 (R²)":
            st.info("💡 표준용액 농도(X)와 측정값(Y)을 입력하세요.")
            default_data = pd.DataFrame([
                {"농도(X)": 0.0, "측정값(Y)": 0.0},
                {"농도(X)": 5.0, "측정값(Y)": 5.1},
                {"농도(X)": 10.0, "측정값(Y)": 9.8},
                {"농도(X)": 20.0, "측정값(Y)": 20.2},
            ])
            edited_df = st.data_editor(default_data, num_rows="dynamic", use_container_width=True)
            
            if st.button("🚀 계산 실행", type="primary", use_container_width=True):
                x_vals = edited_df["농도(X)"].tolist()
                y_vals = edited_df["측정값(Y)"].tolist()
                
                res, err = calculate_linearity(x_vals, y_vals)
                
                if err: st.error(f"오류: {err}")
                else:
                    r2 = res['R2']
                    c_res1, c_res2 = st.columns(2)
                    c_res1.metric("결정계수 (R²)", f"{r2:.4f}")
                    c_res2.info(f"회귀식: {res['equation']}")
                    
                    if r2 >= criteria:
                        st.markdown(f'<div class="pass-box">✅ 적합 (PASS)</div>', unsafe_allow_html=True)
                        st.balloons()
                    else:
                        st.markdown(f'<div class="fail-box">❌ 부적합 (FAIL)</div>', unsafe_allow_html=True)

        # [B] 정확도/반복성 검사 로직
        else:
            st.info("💡 참값(조제농도) 1개와 n번의 측정값을 입력하세요.")
            true_val = st.number_input("표준용액 조제 농도 (참값)", value=10.0)
            raw_meas = st.text_input("측정값 (콤마로 구분)", "10.1, 9.9, 10.2, 10.0")
            
            if st.button("🚀 계산 실행", type="primary", use_container_width=True):
                try:
                    m_vals = [float(x) for x in re.split(r'[,\s]+', raw_meas.strip()) if x]
                    res = calculate_precision_accuracy(true_val, m_vals)
                    
                    if res:
                        acc = res['accuracy_error']
                        rsd = res['rsd']
                        
                        r1, r2, r3 = st.columns(3)
                        r1.metric("평균값", f"{res['average']:.2f}")
                        r2.metric("오차율(정확도)", f"{acc:.2f}%")
                        r3.metric("RSD(반복성)", f"{rsd:.2f}%")
                        
                        is_pass_acc = acc <= crit_acc
                        is_pass_rsd = rsd <= crit_rsd
                        
                        if is_pass_acc and is_pass_rsd:
                            st.markdown(f'<div class="pass-box">✅ 최종 적합 (PASS)</div>', unsafe_allow_html=True)
                            st.balloons()
                        else:
                            reasons = []
                            if not is_pass_acc: reasons.append("정확도 미달")
                            if not is_pass_rsd: reasons.append("반복성 미달")
                            st.markdown(f'<div class="fail-box">❌ 부적합 ({", ".join(reasons)})</div>', unsafe_allow_html=True)
                    else: st.error("입력값이 올바르지 않습니다.")
                except: st.error("숫자만 입력해주세요.")
