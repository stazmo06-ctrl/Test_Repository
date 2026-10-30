import math

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine, text

# ---------- Config ----------
DB_NAME = "EmployeeDB"
DB_USER = "postgres"
DB_PASSWORD = "Superuser2006"   # put your real password here to run locally; reset before submitting
DB_HOST = "localhost"
DB_PORT = "5432"

st.set_page_config(page_title="KLB Employee Dashboard", layout="wide")


# ---------- Engineering: cached engine and cached queries ----------
@st.cache_resource
def get_engine():
    return create_engine(
        f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )


@st.cache_data
def run_query(sql, params=None):
    return pd.read_sql(text(sql), get_engine(), params=params)


# ---------- Sidebar filter options (from the database) ----------
all_divisions = run_query("SELECT divtype FROM divisions ORDER BY divtype")["divtype"].tolist()
all_departments = run_query("SELECT departmentname FROM departments ORDER BY departmentname")[
    "departmentname"
].tolist()
sal_range = run_query("SELECT MIN(salary) AS lo, MAX(salary) AS hi FROM employeedetails")
sal_min = int(math.floor(float(sal_range["lo"][0])))
sal_max = int(math.ceil(float(sal_range["hi"][0])))

st.sidebar.header("Filters")
sel_divisions = st.sidebar.multiselect("Division", all_divisions, default=all_divisions)
sel_dept = st.sidebar.selectbox("Department", ["All"] + all_departments)
sel_salary = st.sidebar.slider(
    "Salary range ($)", min_value=sal_min, max_value=sal_max,
    value=(sal_min, sal_max), step=1000,
)

if not sel_divisions:
    st.warning("Select at least one division in the sidebar.")
    st.stop()

# Filter values reach SQL as parameters, never pasted into the SQL string.
params = {
    "divs": sel_divisions,
    "dept": None if sel_dept == "All" else sel_dept,
    "lo": sel_salary[0],
    "hi": sel_salary[1],
}

# Shared FROM/WHERE: every query below uses it, so every element follows all three filters.
BASE = """
FROM employeedetails e
JOIN personaldetails p ON p.ssn = e.ssn
JOIN jobtitles j ON j.jobtitleid = e.jobtitleid
JOIN departments d ON d.departmentid = e.departmentid
JOIN divisions dv ON dv.divisionid = e.divisionid
WHERE dv.divtype = ANY(:divs)
  AND (:dept IS NULL OR d.departmentname = :dept)
  AND e.salary BETWEEN :lo AND :hi
"""

st.title("KLB Employee Dashboard")

# ---------- 2. KPI row ----------
kpi = run_query(
    f"""
    SELECT COUNT(*) AS headcount,
           AVG(e.salary) AS avg_salary,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY e.salary) AS median_salary
    {BASE}
    """,
    params,
)

if int(kpi["headcount"][0]) == 0:
    st.warning("No employees match the current filters.")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Headcount", f"{int(kpi['headcount'][0]):,}")
c2.metric("Average salary", f"${float(kpi['avg_salary'][0]):,.0f}")
c3.metric("Median salary", f"${float(kpi['median_salary'][0]):,.0f}")

# ---------- Employee-level rows (used by the box plot and the table) ----------
emp = run_query(
    f"""
    SELECT p.name AS "Name", j.jobtitle AS "Job Title", d.departmentname AS "Department",
           dv.divtype AS "Division", e.salary AS "Salary"
    {BASE}
    ORDER BY e.salary DESC
    """,
    params,
)
emp["Salary"] = emp["Salary"].astype(float)

# ---------- 3. Headcount by department ----------
left, right = st.columns(2)

dept_df = run_query(
    f"""
    SELECT d.departmentname AS department, COUNT(*) AS headcount
    {BASE}
    GROUP BY d.departmentname
    ORDER BY headcount DESC
    """,
    params,
)
fig_dept = px.bar(
    dept_df, x="department", y="headcount",
    title="Headcount by Department",
    labels={"department": "Department", "headcount": "Number of employees"},
)
left.plotly_chart(fig_dept, use_container_width=True)

# ---------- 4. Salary distribution by division (box plot) ----------
fig_box = px.box(
    emp, x="Division", y="Salary",
    title="Salary Distribution by Division",
    labels={"Division": "Division", "Salary": "Salary ($)"},
)
right.plotly_chart(fig_box, use_container_width=True)

# ---------- 5. Average salary by age band ----------
age_df = run_query(
    f"""
    SELECT band AS age_band, COUNT(*) AS employees, AVG(salary) AS avg_salary
    FROM (
        SELECT e.salary,
               CASE
                   WHEN DATE_PART('year', AGE(CURRENT_DATE, p.birthdate)) < 30 THEN 'Under 30'
                   WHEN DATE_PART('year', AGE(CURRENT_DATE, p.birthdate)) < 40 THEN '30-39'
                   WHEN DATE_PART('year', AGE(CURRENT_DATE, p.birthdate)) < 50 THEN '40-49'
                   WHEN DATE_PART('year', AGE(CURRENT_DATE, p.birthdate)) < 60 THEN '50-59'
                   ELSE '60+'
               END AS band
        {BASE}
          AND p.birthdate IS NOT NULL
    ) t
    GROUP BY band
    """,
    params,
)
band_order = ["Under 30", "30-39", "40-49", "50-59", "60+"]
age_df["avg_salary"] = age_df["avg_salary"].astype(float)
age_df["age_band"] = pd.Categorical(age_df["age_band"], categories=band_order, ordered=True)
age_df = age_df.sort_values("age_band")
age_df["label"] = "n=" + age_df["employees"].astype(str)

left2, right2 = st.columns(2)
fig_age = px.bar(
    age_df, x="age_band", y="avg_salary", text="label",
    hover_data={"employees": True},
    category_orders={"age_band": band_order},
    title="Average Salary by Age Band",
    labels={"age_band": "Age band", "avg_salary": "Average salary ($)", "employees": "Employees"},
)
fig_age.update_traces(textposition="outside")
left2.plotly_chart(fig_age, use_container_width=True)

# ---------- 6. Top 10 job titles by average salary ----------
top_df = run_query(
    f"""
    SELECT j.jobtitle AS job_title, AVG(e.salary) AS avg_salary
    {BASE}
    GROUP BY j.jobtitle
    ORDER BY avg_salary DESC
    LIMIT 10
    """,
    params,
)
top_df["avg_salary"] = top_df["avg_salary"].astype(float)
fig_top = px.bar(
    top_df, x="avg_salary", y="job_title", orientation="h",
    title="Top 10 Job Titles by Average Salary",
    labels={"avg_salary": "Average salary ($)", "job_title": "Job title"},
)
fig_top.update_yaxes(categoryorder="total ascending")   # highest bar at the top
right2.plotly_chart(fig_top, use_container_width=True)

# ---------- 7. Employee table ----------
with st.expander("Employee table", expanded=False):
    st.dataframe(emp, use_container_width=True, hide_index=True)
