import time
import psycopg2
from ..ingestion.helpers import connect_postgres, load_env_vars
from typing import Dict, List, Tuple, Optional
import streamlit as st
from .helpers import connect_postgres, load_env_vars
import pandas as pd

def get_database_overview() -> Optional[Dict]:
    """
    Get comprehensive database statistics and overview information.
    
    Returns:
        Dictionary containing database statistics or None if error occurs
    """
    try:
        env = load_env_vars()
        conn = connect_postgres(env)
        cur = conn.cursor()
        
        # Get total records
        cur.execute("SELECT COUNT(*) FROM public.resumes_metadata;")
        total_metadata = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM public.resumes_normal;")
        total_normal = cur.fetchone()[0]
        
        # Get unique candidates
        cur.execute("SELECT COUNT(DISTINCT candidate_key) FROM public.resumes_metadata;")
        unique_candidates = cur.fetchone()[0]
        
        
        # Get skills distribution
        cur.execute("""
            SELECT unnest(skills_categories) as skill, COUNT(*) as count
            FROM public.resumes_normal 
            WHERE skills_categories IS NOT NULL 
            GROUP BY skill 
            ORDER BY count DESC 
            LIMIT 10;
        """)
        top_skills = cur.fetchall()
        
        # Get university distribution
        cur.execute("""
            SELECT university, COUNT(*) as count
            FROM public.resumes_metadata 
            WHERE university IS NOT NULL 
            GROUP BY university 
            ORDER BY count DESC 
            LIMIT 5;
        """)
        top_universities = cur.fetchall()
        
        # Get employment type distribution
        cur.execute("""
            SELECT part_or_full, COUNT(*) as count
            FROM public.resumes_metadata 
            WHERE part_or_full IS NOT NULL 
            GROUP BY part_or_full 
            ORDER BY count DESC;
        """)
        employment_distribution = cur.fetchall()
        
        # Get citizenship distribution
        cur.execute("""
            SELECT citizenship, COUNT(*) as count
            FROM public.resumes_metadata 
            WHERE citizenship IS NOT NULL 
            GROUP BY citizenship 
            ORDER BY count DESC;
        """)
        citizenship_distribution = cur.fetchall()
        
        # Get salary distribution
        cur.execute("""
            SELECT 
                CASE 
                    WHEN salary = 'any' THEN 'Flexible'
                    WHEN salary ~ '^[0-9]+$' THEN
                        CASE 
                            WHEN CAST(salary AS INTEGER) < 1000 THEN '< $1000'
                            WHEN CAST(salary AS INTEGER) < 1200 THEN '$1000-1200'
                            WHEN CAST(salary AS INTEGER) < 1400 THEN '$1200-1400'
                            WHEN CAST(salary AS INTEGER) < 1600 THEN '$1400-1600'
                            ELSE '$1600+'
                        END
                    ELSE 'Other'
                END as salary_range,
                COUNT(*) as count
            FROM public.resumes_metadata 
            WHERE salary IS NOT NULL 
            GROUP BY salary_range 
            ORDER BY count DESC;
        """)
        salary_distribution = cur.fetchall()
        
        cur.close()
        conn.close()
        
        return {
            'total_metadata': total_metadata,
            'total_normal': total_normal,
            'unique_candidates': unique_candidates,
            'top_skills': top_skills,
            'top_universities': top_universities,
            'employment_distribution': employment_distribution,
            'citizenship_distribution': citizenship_distribution,
            'salary_distribution': salary_distribution
        }
        
    except Exception as e:
        st.error(f"Error fetching database overview: {e}")
        return None

def render_overview_dashboard() -> None:
    """
    Render the complete overview dashboard in Streamlit.
    This is a comprehensive view of the entire database.
    """
    st.markdown("### 📊 Database Overview Dashboard")
    st.caption("Comprehensive view of your resume database statistics and insights")
    
    # Fetch database stats
    db_overview = get_database_overview()
    
    if not db_overview:
        st.error("❌ Unable to fetch database overview")
        return
    
    # === TOP METRICS ROW ===
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📄 Total Resumes", db_overview['total_metadata'])
    with col2:
        st.metric("🔍 Processed Resumes", db_overview['total_normal'])
    with col3:
        st.metric("👥 Unique Candidates", db_overview['unique_candidates'])
    with col4:
        sync_rate = f"{(db_overview['total_normal']/max(db_overview['total_metadata'], 1)*100):.1f}%"
        st.metric("🔄 Sync Rate", sync_rate)
    
    st.markdown("---")
    
    # === DISTRIBUTIONS AND ANALYTICS ===
    tab1, tab2 = st.tabs(["📊 Demographics", "🛠️ Skills & Experience"])
    
    with tab1:
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### 🎓 University Distribution")
            if db_overview['top_universities']:
                uni_data = {
                    "University": [row[0] for row in db_overview['top_universities']],
                    "Count": [row[1] for row in db_overview['top_universities']]
                }
                st.dataframe(uni_data, hide_index=True, use_container_width=True)
            else:
                st.info("No university data available")
            
            st.markdown("#### 🌍 Citizenship Distribution")
            if db_overview['citizenship_distribution']:
                citizen_data = {
                    "Citizenship": [row[0] for row in db_overview['citizenship_distribution']],
                    "Count": [row[1] for row in db_overview['citizenship_distribution']]
                }
                st.dataframe(citizen_data, hide_index=True, use_container_width=True)
                
                # Show as pie chart
                st.bar_chart(dict(db_overview['citizenship_distribution']))
            else:
                st.info("No citizenship data available")
        
        with col2:
            st.markdown("#### 👔 Employment Type Distribution")
            if db_overview['employment_distribution']:
                emp_data = {
                    "Type": [row[0] for row in db_overview['employment_distribution']],
                    "Count": [row[1] for row in db_overview['employment_distribution']]
                }
                st.dataframe(emp_data, hide_index=True, use_container_width=True)
                
                # Show as bar chart
                st.bar_chart(dict(db_overview['employment_distribution']))
            else:
                st.info("No employment type data available")
            
            st.markdown("#### 💰 Salary Distribution")
            if db_overview['salary_distribution']:
                salary_data = {
                    "Range": [row[0] for row in db_overview['salary_distribution']],
                    "Count": [row[1] for row in db_overview['salary_distribution']]
                }
                st.dataframe(salary_data, hide_index=True, use_container_width=True)
            else:
                st.info("No salary data available")
    
    with tab2:
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.markdown("#### 🛠️ Top Skills")
            if db_overview['top_skills']:
                skills_data = {
                    "Skill": [row[0] for row in db_overview['top_skills']],
                    "Candidates": [row[1] for row in db_overview['top_skills']]
                }
                st.dataframe(skills_data, hide_index=True, use_container_width=True, height=400)
                
                # Show as horizontal bar chart
                skills_dict = {row[0]: row[1] for row in db_overview['top_skills']}
                st.bar_chart(skills_dict)
            else:
                st.info("No skills data available")
        
        with col2:
            st.markdown("#### 📈 Quick Stats")
            
            # Additional calculated metrics
            if db_overview['total_metadata'] > 0:
                avg_resumes_per_candidate = db_overview['total_metadata'] / db_overview['unique_candidates']
                st.metric("📊 Avg Resumes/Candidate", f"{avg_resumes_per_candidate:.1f}")
            
            if db_overview['top_skills']:
                total_skill_mentions = sum(row[1] for row in db_overview['top_skills'])
                st.metric("🎯 Top 10 Skills Total", total_skill_mentions)
                
                most_popular_skill = db_overview['top_skills'][0]
                st.metric("🥇 Most Popular Skill", f"{most_popular_skill[0]} ({most_popular_skill[1]})")
            
            # Data quality indicators
            processing_completeness = f"{sync_rate}"
            st.metric("✅ Processing Complete", processing_completeness)
    

def get_quick_stats() -> Optional[Dict[str, int]]:
    """
    Get quick database statistics for use in other parts of the application.
    
    Returns:
        Dictionary with basic statistics or None if error occurs
    """
    try:
        env = load_env_vars()
        conn = connect_postgres(env)
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM public.resumes_metadata;")
        total_metadata = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM public.resumes_normal;")
        total_normal = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(DISTINCT candidate_key) FROM public.resumes_metadata;")
        unique_candidates = cur.fetchone()[0]
        
        cur.close()
        conn.close()
        
        return {
            'total_metadata': total_metadata,
            'total_normal': total_normal,
            'unique_candidates': unique_candidates
        }
        
    except Exception as e:
        st.error(f"Error fetching quick stats: {e}")
        return None
    
def get_all_candidate_keys() -> List[str]:
    """
    Get all unique candidate keys from both resumes_metadata and resumes_normal tables.
    
    Returns:
        List of unique candidate keys
    """
    try:
        env = load_env_vars()
        conn = connect_postgres(env)
        cur = conn.cursor()
        
        # Get candidate keys from both tables
        cur.execute("""
            SELECT DISTINCT candidate_key 
            FROM (
                SELECT candidate_key FROM public.resumes_metadata 
                WHERE candidate_key IS NOT NULL
                UNION
                SELECT candidate_key FROM public.resumes_normal 
                WHERE candidate_key IS NOT NULL
            ) AS combined_keys
            ORDER BY candidate_key;
        """)
        
        candidate_keys = [row[0] for row in cur.fetchall()]
        
        cur.close()
        conn.close()
        
        return candidate_keys
        
    except Exception as e:
        st.error(f"Error fetching candidate keys: {e}")
        return []

def get_candidate_details(candidate_key: str) -> Dict:
    """
    Get detailed information about a specific candidate from both tables.
    
    Args:
        candidate_key: The candidate identifier
        
    Returns:
        Dictionary with candidate details from both tables
    """
    try:
        env = load_env_vars()
        conn = connect_postgres(env)
        cur = conn.cursor()
        
        # Get metadata records
        cur.execute("""
            SELECT filename, university, applied_position, salary, part_or_full, citizenship
            FROM public.resumes_metadata 
            WHERE candidate_key = %s;
        """, (candidate_key,))
        metadata_records = cur.fetchall()
        
        # Get normal records
        cur.execute("""
            SELECT filename, skills_categories
            FROM public.resumes_normal 
            WHERE candidate_key = %s;
        """, (candidate_key,))
        normal_records = cur.fetchall()
        
        cur.close()
        conn.close()
        
        return {
            'candidate_key': candidate_key,
            'metadata_records': metadata_records,
            'normal_records': normal_records,
            'total_files': len(set([r[0] for r in metadata_records] + [r[0] for r in normal_records]))
        }
        
    except Exception as e:
        st.error(f"Error fetching candidate details: {e}")
        return {}

# def delete_candidate_records(candidate_key: str) -> Dict[str, int]:
#     """
#     Delete all records for a specific candidate from both tables.
    
#     Args:
#         candidate_key: The candidate identifier to delete
        
#     Returns:
#         Dictionary with deletion counts from both tables
#     """
#     try:
#         env = load_env_vars()
#         conn = connect_postgres(env)
#         cur = conn.cursor()
        
#         # Delete from resumes_metadata
#         cur.execute("""
#             DELETE FROM public.resumes_metadata 
#             WHERE candidate_key = %s;
#         """, (candidate_key,))
#         metadata_deleted = cur.rowcount
        
#         # Delete from resumes_normal
#         cur.execute("""
#             DELETE FROM public.resumes_normal 
#             WHERE candidate_key = %s;
#         """, (candidate_key,))
#         normal_deleted = cur.rowcount
        
#         conn.commit()
#         cur.close()
#         conn.close()
        
#         return {
#             'metadata_deleted': metadata_deleted,
#             'normal_deleted': normal_deleted,
#             'total_deleted': metadata_deleted + normal_deleted
#         }
        
#     except Exception as e:
#         st.error(f"Error deleting candidate records: {e}")
#         return {'metadata_deleted': 0, 'normal_deleted': 0, 'total_deleted': 0}

def delete_candidate_records(candidate_key: str) -> Dict[str, int]:
    """
    Delete all records for a specific candidate from metadata, normal, and score tables.
    """
    try:
        env = load_env_vars()
        conn = connect_postgres(env)
        cur = conn.cursor()

        # 1) Delete from resumes_metadata
        cur.execute("""
            DELETE FROM public.resumes_metadata
            WHERE candidate_key = %s;
        """, (candidate_key,))
        metadata_deleted = cur.rowcount

        # 2) Delete from resumes_normal
        cur.execute("""
            DELETE FROM public.resumes_normal
            WHERE candidate_key = %s;
        """, (candidate_key,))
        normal_deleted = cur.rowcount

        # 3) Delete from resume_category_score
        cur.execute("""
            DELETE FROM public.resume_category_score
            WHERE candidate_key = %s;
        """, (candidate_key,))
        score_deleted = cur.rowcount

        conn.commit()
        cur.close()
        conn.close()

        return {
            'metadata_deleted': metadata_deleted,
            'normal_deleted': normal_deleted,
            'score_deleted':    score_deleted,
            'total_deleted':    metadata_deleted + normal_deleted + score_deleted,
        }

    except Exception as e:
        st.error(f"Error deleting candidate records: {e}")
        return {
            'metadata_deleted': 0,
            'normal_deleted':   0,
            'score_deleted':    0,
            'total_deleted':    0,
        }


def render_deletion_tab() -> None:
    """
    Render the deletion tab with candidate management functionality.
    """
    st.markdown("### 🗑️ Candidate Record Deletion")
    st.caption("⚠️ **Warning**: This will permanently delete all records for the selected candidate from both tables!")
    
    # Get all candidate keys
    candidate_keys = get_all_candidate_keys()
    
    if not candidate_keys:
        st.info("📭 No candidate records found in the database.")
        return
    
    st.info(f"📊 Found **{len(candidate_keys)}** candidates in the database")
    
    # Create two columns for selection and preview
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown("#### 👤 Select Candidate")
        
        # Selectbox for candidate selection
        selected_candidate = st.selectbox(
            "Choose candidate to delete:",
            options=[""] + candidate_keys,
            index=0,
            help="Select a candidate to view their details and delete their records"
        )
    
    with col2:
        if selected_candidate:
            st.markdown("#### 📋 Candidate Details")
            
            # Get detailed information about the selected candidate
            candidate_details = get_candidate_details(selected_candidate)
            
            if candidate_details:
                # Display summary metrics
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    st.metric("📁 Total Files", candidate_details['total_files'])
                with col_b:
                    st.metric("📊 Metadata Records", len(candidate_details['metadata_records']))
                with col_c:
                    st.metric("🔍 Skills Records", len(candidate_details['normal_records']))
                
                # Show detailed records
                if candidate_details['metadata_records']:
                    st.markdown("##### 📊 Metadata Records")
                    metadata_df = {
                        "Filename": [r[0] for r in candidate_details['metadata_records']],
                        "University": [r[1] or "N/A" for r in candidate_details['metadata_records']],
                        "Position": [r[2] or "N/A" for r in candidate_details['metadata_records']],
                        "Salary": [r[3] or "N/A" for r in candidate_details['metadata_records']],
                        "Employment": [r[4] or "N/A" for r in candidate_details['metadata_records']],
                        "Citizenship": [r[5] or "N/A" for r in candidate_details['metadata_records']]
                    }
                    st.dataframe(metadata_df, hide_index=True, use_container_width=True)
                
                if candidate_details['normal_records']:
                    st.markdown("##### 🛠️ Skills Records")
                    normal_df = {
                        "Filename": [r[0] for r in candidate_details['normal_records']],
                        "Skills": [", ".join(r[1][:5]) + ("..." if len(r[1]) > 5 else "") if r[1] else "N/A" 
                                 for r in candidate_details['normal_records']]
                    }
                    st.dataframe(normal_df, hide_index=True, use_container_width=True)
                
                st.markdown("---")
                
                # Deletion section with confirmation
                st.markdown("##### ⚠️ Danger Zone")
                
                # Two-step confirmation process
                confirm_checkbox = st.checkbox(
                    f"I understand that deleting **{selected_candidate}** will permanently remove all their records",
                    key=f"confirm_{selected_candidate}"
                )
                
                if confirm_checkbox:
                    st.error("🚨 **Final Warning**: This action cannot be undone!")
                    
                    delete_button = st.button(
                        f"🗑️ DELETE {selected_candidate}",
                        type="primary",
                        use_container_width=True,
                        key=f"delete_{selected_candidate}"
                    )
                    
                    if delete_button:
                        with st.spinner(f"🗑️ Deleting all records for {selected_candidate}..."):
                            deletion_result = delete_candidate_records(selected_candidate)
                        
                        if deletion_result['total_deleted'] > 0:
                            st.success(
                                f"✅ **Successfully deleted {selected_candidate}!**\n\n"
                                f"📊 Metadata records deleted: {deletion_result['metadata_deleted']}\n\n"
                                f"🔍 Skills records deleted: {deletion_result['normal_deleted']}\n\n"
                                f"🏷️ Category‐score rows deleted: {deletion_result['score_deleted']}\n\n"
                                f"📁 Total records deleted: {deletion_result['total_deleted']}"
                            )
                            
                            # Clear the selection by rerunning
                            st.rerun()
                        else:
                            st.error("❌ No records were deleted. Please check if the candidate exists.")
            
            else:
                st.error("❌ Could not retrieve candidate details.")
        else:
            st.info("👆 Select a candidate from the left to view their details")
    
    # Add refresh button
    st.markdown("---")
    col_refresh1, col_refresh2, col_refresh3 = st.columns([1, 1, 1])
    with col_refresh2:
        if st.button("🔄 Refresh Candidate List", use_container_width=True):
            st.rerun()
            
# def render_skills_management_tab() -> None:
#     """
#     Render the skills management tab for viewing and managing skills categories.
#     """
#     st.markdown("### 🛠️ Manage Skill Categories")
#     conn = connect_postgres(load_env_vars())
#     cur  = conn.cursor()

#     # 1) Show existing categories
#     st.write("#### Existing Categories")
#     cur.execute("SELECT id, name FROM skill_category ORDER BY name;")
#     rows = cur.fetchall()
#     if rows:
#         st.table({
#             "ID":   [r[0] for r in rows],
#             "Name": [r[1].title() for r in rows],
#         })
        
#         # Show count
#         st.info(f"📊 Total categories: **{len(rows)}**")
#     else:
#         st.info("No skill categories defined yet.")

#     st.markdown("---")

#     # 2) Show previous alert once
#     if st.session_state.get("cat_success"):
#         st.success(st.session_state["cat_success"])
#         del st.session_state["cat_success"]

#     # 3) Clear the text_input on the one run after adding
#     if st.session_state.get("cat_added", False):
#         default_new_cat = ""
#         del st.session_state["cat_added"]
#     else:
#         default_new_cat = st.session_state.get("new_cat_input", "")

#     # 4) Add a new category with existence check
#     st.markdown("#### ➕ Add New Category")
#     new_cat = st.text_input(
#         "Add a new category",
#         placeholder="e.g. Web Development",
#         key="new_cat_input",
#         value=default_new_cat,
#     )
#     if st.button("➕ Add Category", key="add_cat_btn"):
#         cat = new_cat.strip()
#         if not cat:
#             st.error("Name cannot be empty.")
#         else:
#             # Try to insert, returning the name if inserted
#             cur.execute("""
#                 INSERT INTO skill_category(name)
#                 VALUES (LOWER(%s))
#                 ON CONFLICT(name) DO NOTHING
#                 RETURNING name;
#             """, (cat,))
#             result = cur.fetchone()
#             if result:
#                 # insertion happened
#                 conn.commit()
#                 st.session_state["cat_success"] = f"Added category: **{cat}**"
#                 st.session_state["cat_added"]   = True
#             else:
#                 # already existed
#                 st.session_state["cat_success"] = f"Category **{cat}** already exists."
#             st.rerun()

#     st.markdown("---")

#     # 5) Show previous delete alert once
#     if st.session_state.get("del_success"):
#         st.warning(st.session_state["del_success"])
#         del st.session_state["del_success"]

#     # 6) Delete an existing category
#     if rows:  # Only show if there are categories to delete
#         st.markdown("#### 🗑️ Delete Individual Category")
#         to_delete = st.selectbox(
#             "Delete a category",
#             [r[1].title() for r in rows],
#             index=0 if rows else None
#         )
#         if st.button("🗑️ Delete Category", key="del_cat_btn"):
#             cur.execute(
#                 "DELETE FROM skill_category WHERE LOWER(name) = LOWER(%s);",
#                 (to_delete,)
#             )
#             conn.commit()
#             st.session_state["del_success"] = f"Deleted category: **{to_delete}**"
#             st.rerun()

#     st.markdown("---")

#     # 7) NEW: Delete All Categories section
#     st.markdown("#### 🧹 Bulk Delete All Categories")
#     st.warning("⚠️ This will permanently delete **all** skill categories. Use this before ingesting a new job description.")
    
#     # Show delete all success message
#     if st.session_state.get("delete_all_cats_success", False):
#         st.success("✅ All skill categories have been deleted.")
#         del st.session_state["delete_all_cats_success"]

#     # Handle confirmation checkbox
#     if st.session_state.get("deleted_all_cats_once", False):
#         default_confirm_all = False
#         del st.session_state["deleted_all_cats_once"]
#     else:
#         default_confirm_all = st.session_state.get("confirm_delete_all_cats", False)

#     confirm_delete_all = st.checkbox(
#         "I understand this will delete all skill categories and cannot be undone",
#         value=default_confirm_all,
#         key="confirm_delete_all_cats",
#     )

#     if st.button("🗑️ DELETE ALL CATEGORIES", key="delete_all_cats_btn", type="secondary"):
#         if not confirm_delete_all:
#             st.error("You must check the confirmation box above to delete all categories.")
#         else:
#             try:
#                 # Count categories before deletion
#                 cur.execute("SELECT COUNT(*) FROM skill_category;")
#                 count_before = cur.fetchone()[0]
                
#                 # Delete all categories
#                 cur.execute("TRUNCATE TABLE skill_category RESTART IDENTITY CASCADE;")
#                 conn.commit()
                
#                 # Set success flags
#                 st.session_state["delete_all_cats_success"] = True
#                 st.session_state["deleted_all_cats_once"] = True
                
#                 st.rerun()
                
#             except Exception as e:
#                 st.error(f"❌ Failed to delete all categories: {e}")

#     cur.close()
#     conn.close()

def render_skills_management_tab() -> None:
    """
    Render the skills management tab for viewing and managing skills categories.
    """
    print("🔧" * 30)
    print("render_skills_management_tab() CALLED!")
    print("🔧" * 30)
    
    st.markdown("### 🛠️ Manage Skill Categories")
    conn = connect_postgres(load_env_vars())
    cur = conn.cursor()

    # 1) Show existing categories
    st.write("#### Existing Categories")
    cur.execute("SELECT id, name FROM skill_category ORDER BY name;")
    rows = cur.fetchall()
    
    print(f"📊 Found {len(rows)} existing skill categories")
    
    if rows:
        st.table({
            "ID": [r[0] for r in rows],
            "Name": [r[1].title() for r in rows],
        })
        
        # Show count
        st.info(f"📊 Total categories: **{len(rows)}**")
    else:
        st.info("No skill categories defined yet.")

    st.markdown("---")

    # 2) Show previous alert once
    if st.session_state.get("cat_success"):
        st.success(st.session_state["cat_success"])
        del st.session_state["cat_success"]

    # 3) Clear the text_input on the one run after adding
    if st.session_state.get("cat_added", False):
        default_new_cat = ""
        del st.session_state["cat_added"]
    else:
        default_new_cat = st.session_state.get("new_cat_input", "")

    # 4) Add a new category with existence check
    st.markdown("#### ➕ Add New Category")
    new_cat = st.text_input(
        "Add a new category",
        placeholder="e.g. Web Development",
        key="new_cat_input",
        value=default_new_cat,
    )
    if st.button("➕ Add Category", key="add_cat_btn"):
        cat = new_cat.strip()
        print(f"🆕 Attempting to add category: '{cat}'")
        
        if not cat:
            print("❌ Category name is empty")
            st.session_state["cat_success"] = "❌ Name cannot be empty."
        else:
            try:
                # Try to insert, returning the name if inserted
                cur.execute("""
                    INSERT INTO skill_category(name)
                    VALUES (LOWER(%s))
                    ON CONFLICT(name) DO NOTHING
                    RETURNING name;
                """, (cat,))
                result = cur.fetchone()
                
                if result:
                    # insertion happened
                    conn.commit()
                    print(f"✅ Successfully added category: '{cat}'")
                    st.session_state["cat_success"] = f"Added category: **{cat}**"
                    st.session_state["cat_added"] = True
                else:
                    # already existed
                    print(f"⚠️ Category already exists: '{cat}'")
                    st.session_state["cat_success"] = f"Category **{cat}** already exists."
                
                st.rerun()
                
            except Exception as e:
                print(f"❌ Error adding category: {e}")
                st.session_state["cat_success"] = f"❌ Error adding category: {e}"
                st.rerun()

    st.markdown("---")

    # 5) Show previous delete alert once
    if st.session_state.get("del_success"):
        st.info(st.session_state["del_success"])  # Changed from st.warning to st.info
        del st.session_state["del_success"]

    # 6) Delete an existing category
    if rows:  # Only show if there are categories to delete
        st.markdown("#### 🗑️ Delete Individual Category")
        to_delete = st.selectbox(
            "Delete a category",
            [r[1].title() for r in rows],
            index=0 if rows else None
        )
        if st.button("🗑️ Delete Category", key="del_cat_btn"):
            print(f"🗑️ Attempting to delete category: '{to_delete}'")
            
            try:
                cur.execute(
                    "DELETE FROM skill_category WHERE LOWER(name) = LOWER(%s);",
                    (to_delete,)
                )
                deleted_count = cur.rowcount
                conn.commit()
                
                print(f"✅ Successfully deleted {deleted_count} category: '{to_delete}'")
                st.session_state["del_success"] = f"Deleted category: **{to_delete}**"
                st.rerun()
                
            except Exception as e:
                print(f"❌ Error deleting category: {e}")
                st.session_state["del_success"] = f"❌ Error deleting category: {e}"
                st.rerun()

    st.markdown("---")

    # 7) NEW: Delete All Categories section
    st.markdown("#### 🧹 Bulk Delete All Categories")
    st.info("⚠️ This will permanently delete **all** skill categories. Use this before ingesting a new job description.")
    
    # Show delete all success message
    if st.session_state.get("delete_all_cats_success", False):
        st.success("✅ All skill categories have been deleted.")
        del st.session_state["delete_all_cats_success"]

    # Handle confirmation checkbox
    if st.session_state.get("deleted_all_cats_once", False):
        default_confirm_all = False
        del st.session_state["deleted_all_cats_once"]
    else:
        default_confirm_all = st.session_state.get("confirm_delete_all_cats", False)

    confirm_delete_all = st.checkbox(
        "I understand this will delete all skill categories and cannot be undone",
        value=default_confirm_all,
        key="confirm_delete_all_cats",
    )

    if st.button("🗑️ DELETE ALL CATEGORIES", key="delete_all_cats_btn", type="secondary"):
        if not confirm_delete_all:
            print("❌ User tried to delete all without confirmation")
            st.session_state["delete_all_cats_success"] = False
            st.session_state["del_success"] = "❌ You must check the confirmation box above to delete all categories."
            st.rerun()
        else:
            print("🗑️ Attempting to delete ALL categories...")
            
            try:
                # Count categories before deletion
                cur.execute("SELECT COUNT(*) FROM skill_category;")
                count_before = cur.fetchone()[0]
                print(f"📊 Found {count_before} categories to delete")
                
                # Delete all categories
                cur.execute("TRUNCATE TABLE skill_category RESTART IDENTITY CASCADE;")
                conn.commit()
                
                print(f"✅ Successfully deleted all {count_before} categories")
                
                # Set success flags
                st.session_state["delete_all_cats_success"] = True
                st.session_state["deleted_all_cats_once"] = True
                
                st.rerun()
                
            except Exception as e:
                print(f"❌ Error deleting all categories: {e}")
                st.session_state["del_success"] = f"❌ Failed to delete all categories: {e}"
                st.rerun()

    cur.close()
    conn.close()
    print("🔧 render_skills_management_tab() completed")
    
   
# def render_score_table() -> None:
#     """
#     Render the skill category scores for each resume.
#     """
#     st.markdown("### 📈 Candidate Skill Category Scores")

#     # —– Fetch data from Postgres —–
#     env  = load_env_vars()
#     conn = connect_postgres(env)
#     cur  = conn.cursor()
#     cur.execute("""
#         SELECT 
#           s.candidate_key || ' / ' || s.filename AS resume_id,
#           c.name AS category,
#           s.score
#         FROM resume_category_score s
#         JOIN skill_category c ON c.id = s.category_id
#     """)
#     rows = cur.fetchall()
#     cur.close()
#     conn.close()

#     if not rows:
#         st.info("No category scores yet.")
#     else:
#         # 1) Build the pivot table
#         df    = pd.DataFrame(rows, columns=["resume_id", "category", "score"])
#         pivot = (
#             df.pivot(index="resume_id", columns="category", values="score")
#               .fillna(0)
#               .astype(int)
#         )

#         # 2) Compute an “average score” helper column and sort by it
#         pivot["avg_score"] = pivot.mean(axis=1)
#         pivot = pivot.sort_values("avg_score", ascending=False).drop("avg_score", axis=1)

#         # 3) Page through top N by average score
#         total = len(pivot)
#         show_n = st.slider(
#             "Show top N resumes by average score",
#             min_value=1,
#             max_value=min(50, total),
#             value=min(10, total)
#         )

#         # 4) Display and allow CSV download
#         display_df = pivot.head(show_n)
#         st.dataframe(display_df)
#         csv = display_df.to_csv().encode("utf-8")
#         st.download_button("⬇️ Download CSV", csv, "category_scores.csv", "text/csv")
        

def render_score_table() -> None:
    """
    Render the skill category scores for each resume with search and filters.
    """
    st.markdown("### 📈 Candidate Skill Category Scores")

    # —– Fetch data from Postgres —–
    env  = load_env_vars()
    conn = connect_postgres(env)
    cur  = conn.cursor()
    cur.execute("""
        SELECT 
          s.candidate_key || ' / ' || s.filename AS resume_id,
          s.candidate_key,
          c.name AS category,
          s.score
        FROM resume_category_score s
        JOIN skill_category c ON c.id = s.category_id
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        st.info("No category scores yet.")
        return

    # 1) Build the pivot table
    df = pd.DataFrame(rows, columns=["resume_id", "candidate_key", "category", "score"])
    pivot = (
        df.pivot(index="resume_id", columns="category", values="score")
          .fillna(0)
          .astype(int)
    )
    
    # Add candidate_key column for filtering
    candidate_mapping = df.drop_duplicates('resume_id').set_index('resume_id')['candidate_key']
    pivot['candidate_key'] = candidate_mapping
    
    # 2) Add average score column
    skill_columns = [col for col in pivot.columns if col != 'candidate_key']
    pivot["Average Score"] = pivot[skill_columns].mean(axis=1).round(2)
    
    # 3) Reorder columns: candidate_key, Average Score, then skills (no duplicates)
    other_skills = [col for col in skill_columns if col != 'Average Score']  
    pivot = pivot[['candidate_key', 'Average Score'] + other_skills]
    
    total = len(pivot)
    st.info(f"📊 **{total} candidates** in database")

    # === SEARCH AND FILTER SECTION ===
    st.markdown("#### 🔍 Search & Filter")
    
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        # Search by candidate name
        search_term = st.text_input(
            "🔍 Search candidates",
            placeholder="Enter candidate name...",
            help="Search by candidate name (case-insensitive)"
        )
    
    with col2:
        # Filter by minimum score in any category
        min_score_filter = st.selectbox(
            "Minimum score (any skill)",
            options=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            index=0,
            help="Show only candidates with at least this score in ANY skill"
        )
    
    with col3:
        # Sort options
        sort_options = ['Average Score'] + skill_columns
        sort_by = st.selectbox(
            "Sort by",
            options=sort_options,
            index=0,
            help="Column to sort by (descending)"
        )

    # === APPLY FILTERS AND SORTING ===
    filtered_pivot = pivot.copy()
    
    # Apply search filter
    if search_term:
        mask = filtered_pivot['candidate_key'].str.contains(search_term, case=False, na=False)
        filtered_pivot = filtered_pivot[mask]
        st.info(f"🔍 Search results: **{len(filtered_pivot)}** candidates match '{search_term}'")
    
    # Apply minimum score filter
    if min_score_filter > 0:
        mask = (filtered_pivot[skill_columns] >= min_score_filter).any(axis=1)
        filtered_pivot = filtered_pivot[mask]
        st.info(f"📊 Filter results: **{len(filtered_pivot)}** candidates with score ≥{min_score_filter}")
    
    # # CRITICAL FIX: Apply sorting BEFORE pagination
    # filtered_pivot = filtered_pivot.sort_values(sort_by, ascending=False)
    
    # # Show sorting info
    # if sort_by != 'Average Score':
    #     st.info(f"📊 Sorted by **{sort_by}** (highest to lowest)")
    
    # CRITICAL FIX: Apply sorting BEFORE pagination
    filtered_pivot = filtered_pivot.sort_values(sort_by, ascending=False)
    
    # DEBUG: Show what sorting actually produced
    st.write(f"**DEBUG: Top 3 candidates after sorting by {sort_by}:**")
    debug_cols = ['candidate_key', sort_by]
    if sort_by != 'Average Score':
        debug_cols.append('Average Score')
    top_3_debug = filtered_pivot.head(3)[debug_cols]
    st.dataframe(top_3_debug)
    
    # Show sorting info
    if sort_by != 'Average Score':
        st.info(f"📊 Sorted by **{sort_by}** (highest to lowest)")

    if len(filtered_pivot) == 0:
        st.warning("⚠️ No candidates match your search/filter criteria.")
        return

    # === PAGINATION (AFTER SORTING) ===
    st.markdown("#### 📋 Results")
    
    # Pagination controls
    col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
    
    with col1:
        page_size = st.selectbox(
            "Results per page",
            options=[10, 20, 50, 100],
            index=1,  # Default to 20
            key="page_size"
        )
    
    with col2:
        total_pages = (len(filtered_pivot) - 1) // page_size + 1
        
        # Handle button clicks with query parameters (cleaner approach)
        if st.session_state.get("go_to_first", False):
            st.session_state["target_page"] = 1
            del st.session_state["go_to_first"]
        elif st.session_state.get("go_to_last", False):
            st.session_state["target_page"] = total_pages  
            del st.session_state["go_to_last"]
        
        # Get target page or use current value
        initial_page = st.session_state.get("target_page", 1)
        if "target_page" in st.session_state:
            del st.session_state["target_page"]
        
        current_page = st.number_input(
            f"Page (1-{total_pages})",
            min_value=1,
            max_value=total_pages,
            value=min(initial_page, total_pages),  # Ensure within bounds
            key="current_page"
        )
    
    with col3:
        st.metric("Showing", f"{len(filtered_pivot)} candidates")
        # Show current sort status
        if sort_by == 'Average Score':
            st.caption("🔄 Default sort")
        else:
            st.caption(f"📊 By {sort_by}")
    
    with col4:
        # Quick jump to top/bottom - with conditional enabling
        col_a, col_b = st.columns(2)
        with col_a:
            # Disable "First Page" if already on page 1
            first_page_disabled = (current_page <= 1)
            if st.button(
                "⬆️ First Page", 
                use_container_width=True, 
                disabled=first_page_disabled,
                help="Go to first page" if not first_page_disabled else "Already on first page"
            ):
                st.session_state["go_to_first"] = True
                st.rerun()
        with col_b:
            # Disable "Last Page" if already on last page
            last_page_disabled = (current_page >= total_pages)
            if st.button(
                "⬇️ Last Page", 
                use_container_width=True, 
                disabled=last_page_disabled,
                help="Go to last page" if not last_page_disabled else "Already on last page"
            ):
                st.session_state["go_to_last"] = True
                st.rerun()

    # === DISPLAY PAGINATED RESULTS (AFTER SORTING) ===
    start_idx = (current_page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_df = filtered_pivot.iloc[start_idx:end_idx]
    
    # Show pagination info with sort context
    total_filtered = len(filtered_pivot)
    st.info(f"📄 Showing entries {start_idx + 1}-{min(end_idx, total_filtered)} of {total_filtered} candidates (sorted by {sort_by})")

    # Remove candidate_key from display (used for filtering only)
    display_df = paginated_df.drop('candidate_key', axis=1)

    st.dataframe(display_df, use_container_width=True, height=600)


    # === SUMMARY STATISTICS FOR CURRENT VIEW ===
    st.markdown("#### 📊 Current View Statistics")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        avg_of_averages = paginated_df['Average Score'].mean()
        st.metric("📈 Avg Score", f"{avg_of_averages:.2f}")
    
    with col2:
        top_performer = paginated_df['Average Score'].max()
        st.metric("🏆 Highest Avg", f"{top_performer:.2f}")
    
    with col3:
        # Find skill with highest max score in current view
        skill_maxes = paginated_df[skill_columns].max()
        best_skill = skill_maxes.idxmax()
        best_score = skill_maxes.max()
        st.metric("🎯 Best Skill Score", f"{best_score}")
        st.caption(f"in {best_skill}")
    
    with col4:
        # Count candidates with score >= 8 in any skill
        high_performers = (paginated_df[skill_columns] >= 8).any(axis=1).sum()
        st.metric("⭐ High Performers", f"{high_performers}")
        st.caption("(score ≥8 in any skill)")

    # === DOWNLOAD OPTIONS ===
    st.markdown("---")
    col1, col2 = st.columns(2)
    
    with col1:
        # Download current filtered results
        csv_filtered = filtered_pivot.drop('candidate_key', axis=1).to_csv().encode("utf-8")
        st.download_button(
            "⬇️ Download Filtered Results",
            csv_filtered,
            f"candidate_scores_filtered_{len(filtered_pivot)}_results.csv",
            "text/csv",
            use_container_width=True
        )
    
    with col2:
        # Download all results
        csv_all = pivot.drop('candidate_key', axis=1).to_csv().encode("utf-8")
        st.download_button(
            "⬇️ Download All Results",
            csv_all,
            f"candidate_scores_all_{total}_candidates.csv",
            "text/csv",
            use_container_width=True
        )



def render_delete_all_resumes() -> None:
    """
    Render the delete all resumes functionality.
    """
    st.markdown("---")
    st.markdown("### 🧹 Bulk Delete All Data")
    st.warning("⚠️ This will permanently erase **all** candidate and resume data. Use with extreme caution!")

    # ── A) If we just succeeded, show banner and clear flag ───────────
    if st.session_state.get("delete_success", False):
        st.success("✅ All records have been deleted.")
        # clear so it only shows once
        del st.session_state["delete_success"]

    # ── B) Handle the confirm checkbox default (cleared after delete) ──
    if st.session_state.get("deleted_all_once", False):
        default_confirm = False
        del st.session_state["deleted_all_once"]
    else:
        default_confirm = st.session_state.get("confirm_delete_all", False)

    confirm = st.checkbox(
        "I understand this cannot be undone",
        value=default_confirm,
        key="confirm_delete_all",
    )

    # ── C) Single “Delete All” button ───────────────────────────────
    if st.button("🗑️ DELETE ALL RECORDS", key="delete_all_btn"):
        if not confirm:
            st.error("You must check the box above to delete everything.")
        else:
            try:
                env  = load_env_vars()
                conn = connect_postgres(env)
                cur  = conn.cursor()
                cur.execute("""
                    TRUNCATE TABLE
                      public.resumes_metadata,
                      public.resumes_normal,
                      public.resume_category_score
                    RESTART IDENTITY CASCADE;
                """)
                conn.commit()
                cur.close()
                conn.close()

                # instead of st.success(), set a flag and rerun
                st.session_state["delete_success"]   = True
                st.session_state["deleted_all_once"] = True
                st.rerun()

            except Exception as e:
                st.error(f"❌ Failed to delete all records: {e}")
    
def render_job_description_main_content() -> None:
    """Main content area for job description processing."""
    print("🔥" * 30)
    print("render_job_description_main_content() CALLED!")
    print("🔥" * 30)
    
    st.markdown("### 📄 Job Description Analysis")
    st.markdown("Upload a job description PDF to extract required skills and save them to the database.")
    
    uploaded_file = st.file_uploader(
        "Choose a job description PDF",
        type=["pdf"],
        help="Upload a PDF containing the job description to analyze"
    )
    
    print(f"📁 File uploaded: {uploaded_file is not None}")
    if uploaded_file:
        print(f"📁 File name: {uploaded_file.name}")
        print(f"📁 File size: {uploaded_file.size}")
    
    if uploaded_file is not None:
        print("🚀 Starting job description processing...")
        try:
            process_job_description_pdf(uploaded_file)
            print("✅ Job description processing completed")
        except Exception as e:
            print(f"❌ Error in process_job_description_pdf: {e}")
            st.error(f"Error processing job description: {e}")
    else:
        print("⏳ Waiting for file upload...")
        st.info("👆 Please upload a job description PDF to begin analysis")

def process_job_description_pdf(uploaded_file):
    """
    Process the uploaded job description PDF and extract skills.
    """
    try:
        # Step 1: Extract text from PDF
        with st.spinner("🔍 Extracting text from PDF..."):
            extracted_text = extract_pdf_text_with_ocr(uploaded_file)
            
            if not extracted_text or len(extracted_text.strip()) < 50:
                print("❌ Could not extract sufficient text from PDF. Please check if the PDF contains readable text.")
                return
            
            st.success(f"✅ Extracted {len(extracted_text)} characters from PDF!")
            
            # Show preview of extracted text
            with st.expander("📖 Preview Extracted Text"):
                preview_text = extracted_text[:2000] + "..." if len(extracted_text) > 2000 else extracted_text
                st.text_area("Full extracted content:", preview_text, height=300, disabled=True)
        
        # Step 2: AI Analysis
        with st.spinner("🤖 Analyzing job requirements with AI..."):
            extracted_skills = extract_skills_from_job_description(extracted_text)
            
            if not extracted_skills:
                print("❌ No skills could be extracted from the job description")
                return
            
            st.success(f"🎯 Found {len(extracted_skills)} skill categories!")
        
        # Step 3: Display extracted skills
        st.markdown("#### 🛠️ Extracted Skills")
        
        # Group skills by category for better display
        skill_categories = categorize_extracted_skills(extracted_skills)
        
        if skill_categories:
            # Create tabs for each category
            tab_names = list(skill_categories.keys())
            tabs = st.tabs(tab_names)
            
            for i, (category, skills) in enumerate(skill_categories.items()):
                with tabs[i]:
                    cols = st.columns(2)
                    mid_point = len(skills) // 2
                    
                    with cols[0]:
                        for skill in skills[:mid_point]:
                            st.write(f"• **{skill}**")
                    
                    with cols[1]:
                        for skill in skills[mid_point:]:
                            st.write(f"• **{skill}**")
        else:
            # Simple two-column layout if categorization fails
            col1, col2 = st.columns(2)
            mid_point = len(extracted_skills) // 2
            
            with col1:
                for skill in extracted_skills[:mid_point]:
                    st.write(f"• **{skill}**")
            
            with col2:
                for skill in extracted_skills[mid_point:]:
                    st.write(f"• **{skill}**")
        
        # Step 4: Save options
        st.markdown("---")
        st.markdown("#### 💾 Save to Database")
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            clear_existing = st.checkbox(
                "🧹 Clear existing skill categories first",
                value=True,
                help="Recommended: Remove all existing skills before adding new ones"
            )
        
        with col2:
            save_button = st.button(
                "💾 Save Skills to Database", 
                type="secondary", 
                use_container_width=True
            )
        
        if save_button:
            print("=" * 60)
            print("DEBUG: Save button clicked!")
            print(f"DEBUG: Skills to save: {extracted_skills}")
            print(f"DEBUG: Clear existing: {clear_existing}")
            print("=" * 60)
            
            with st.spinner("💾 Saving skills to database..."):
                result = save_job_skills_to_database(extracted_skills, clear_existing)
                
                print("-" * 40)
                print(f"DEBUG: Save result: {result}")
                print("-" * 40)
                
                if result['success']:
                    if clear_existing:
                        st.success(f"✅ Cleared {result['deleted_count']} existing skills and saved {result['added_count']} new skill categories!")
                    else:
                        st.success(f"✅ Added {result['added_count']} new skill categories! ({result['duplicate_count']} were already in database)")
                    
                    # Show summary
                    st.balloons()
                    st.info("🔄 Page will refresh to show updated categories...")
                    time.sleep(2)
                    st.rerun()
                else:
                    print(f"❌ Error saving skills: {result.get('error', 'Unknown error')}")
                    
    except Exception as e:
        print(f"❌ Error processing job description: {str(e)}")
        print(f"ERROR in process_job_description_pdf: {e}")
        
# Add all the helper functions here...
def extract_pdf_text_with_ocr(uploaded_file) -> str:
    """Extract text from uploaded PDF file using OCR and text extraction."""
    import fitz  # PyMuPDF
    from pdf2image import convert_from_bytes
    import pytesseract
    from PIL import Image
    import io
    
    try:
        # First, try direct text extraction with PyMuPDF
        pdf_bytes = uploaded_file.read()
        uploaded_file.seek(0)  # Reset file pointer
        
        # Method 1: Direct text extraction
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        direct_text = ""
        
        for page_num in range(doc.page_count):
            page = doc[page_num]
            direct_text += page.get_text()
        
        doc.close()
        
        # If we got good text directly, use it
        if len(direct_text.strip()) > 100:  # Reasonable amount of text
            return direct_text.strip()
        
        # Method 2: OCR if direct extraction failed
        st.info("📸 Direct text extraction yielded limited results. Using OCR...")
        
        # Convert PDF to images
        images = convert_from_bytes(pdf_bytes, dpi=300)
        
        ocr_text = ""
        for i, image in enumerate(images):
            # Use pytesseract for OCR
            page_text = pytesseract.image_to_string(image, lang='eng')
            ocr_text += f"\n--- Page {i+1} ---\n{page_text}"
        
        return ocr_text.strip()
        
    except Exception as e:
        raise Exception(f"Failed to extract text from PDF: {str(e)}")


def extract_skills_from_job_description(job_text: str) -> List[str]:
    """Use AI to extract skill categories from job description text."""
    from ..backend.model import Qwen2VLClient
    
    # Initialize Qwen client
    qwen = Qwen2VLClient(
        host="http://localhost",
        port=8001,
        model="Qwen/Qwen2.5-VL-7B-Instruct",
        temperature=0.0
    )
    
    SKILLS_EXTRACTION_PROMPT = f"""
You are an expert HR analyst. Analyze the following job description and extract ALL technical skills, tools, technologies, and competencies required for this position.

JOB DESCRIPTION:
{job_text}

Your task:
1. Read the job description carefully
2. Extract EVERY technical skill, programming language, framework, tool, platform, methodology, or domain knowledge mentioned
3. Include both explicitly mentioned skills AND implied skills
4. Return ONLY a JSON array of skill names

EXAMPLE OUTPUT:
["Python", "JavaScript", "React", "Node.js", "SQL", "PostgreSQL", "AWS", "Docker", "Git", "Agile", "REST APIs", "Machine Learning", "Data Analysis", "Linux", "CI/CD"]

RULES:
- Include programming languages, frameworks, libraries, databases, cloud platforms, tools, methodologies
- Use standard, widely-recognized names
- Be comprehensive but avoid duplicates
- Don't include soft skills
- Each skill should be 1-4 words maximum
- Return ONLY the JSON array, no additional text

JSON Array of Skills:
"""
    
    try:
        reply = qwen.chat_completion(
            question=SKILLS_EXTRACTION_PROMPT,
            system_prompt="You are an expert at extracting technical skills from job descriptions. Return only clean JSON arrays."
        ).strip()
        
        # Clean up response
        if reply.startswith("```"):
            import re
            json_match = re.search(r'\[.*\]', reply, re.DOTALL)
            if json_match:
                reply = json_match.group(0)
        
        # Parse JSON
        import json
        skills = json.loads(reply)
        
        if isinstance(skills, list):
            # Clean and validate skills
            cleaned_skills = []
            for skill in skills:
                if isinstance(skill, str) and len(skill.strip()) > 0:
                    cleaned_skill = skill.strip().title()  # Proper case
                    if cleaned_skill not in cleaned_skills:  # Avoid duplicates
                        cleaned_skills.append(cleaned_skill)
            
            return cleaned_skills
        else:
            raise ValueError("Response is not a list")
            
    except Exception as e:
        print(f"Error parsing AI response: {e}")
        # Fallback: try to extract skills manually
        return extract_skills_fallback(job_text)
    
def extract_skills_fallback(job_text: str) -> List[str]:
    """Fallback method to extract skills using keyword matching."""
    import re
    
    # Common technical skills to look for
    skill_patterns = [
        r'\b(Python|Java|JavaScript|TypeScript|C\+\+|C#|PHP|Ruby|Go|Kotlin|Swift|Scala|R)\b',
        r'\b(HTML|CSS|React|Vue|Angular|Node\.js|Express|Django|Flask|Laravel|Spring)\b',
        r'\b(SQL|MySQL|PostgreSQL|MongoDB|Redis|Oracle|SQLite)\b',
        r'\b(AWS|Azure|GCP|Docker|Kubernetes|Jenkins|GitLab|CI/CD|Terraform)\b',
        r'\b(Git|GitHub|Jira|Confluence|Linux|Unix|Windows|Mac)\b',
        r'\b(Agile|Scrum|DevOps|TDD|API|REST|GraphQL)\b',
        r'\b(Machine Learning|Data Science|AI|Analytics|Pandas|NumPy|TensorFlow|PyTorch)\b'
    ]
    
    found_skills = set()
    
    for pattern in skill_patterns:
        matches = re.findall(pattern, job_text, re.IGNORECASE)
        for match in matches:
            found_skills.add(match.title())
    
    return list(found_skills) if found_skills else ["Web Development", "Programming", "Database Management"]


def categorize_extracted_skills(skills: List[str]) -> Dict[str, List[str]]:
    """Organize skills into logical categories."""
    categories = {
        "Programming Languages": [],
        "Web Technologies": [],
        "Databases & Storage": [],
        "Cloud & DevOps": [],
        "Tools & Platforms": [],
        "Methodologies": [],
        "Other Skills": []
    }
    
    categorization_rules = {
        "Programming Languages": ["python", "java", "javascript", "typescript", "c++", "c#", "php", "ruby", "go", "kotlin", "swift", "scala", "r"],
        "Web Technologies": ["html", "css", "react", "vue", "angular", "node.js", "express", "django", "flask", "laravel", "spring", "rest", "api"],
        "Databases & Storage": ["sql", "mysql", "postgresql", "mongodb", "redis", "oracle", "sqlite", "database"],
        "Cloud & DevOps": ["aws", "azure", "gcp", "docker", "kubernetes", "jenkins", "gitlab", "ci/cd", "terraform", "devops"],
        "Tools & Platforms": ["git", "github", "jira", "confluence", "linux", "unix", "windows", "mac"],
        "Methodologies": ["agile", "scrum", "tdd", "machine learning", "data science", "ai", "analytics"]
    }
    
    for skill in skills:
        skill_lower = skill.lower()
        categorized = False
        
        for category, keywords in categorization_rules.items():
            if any(keyword in skill_lower for keyword in keywords):
                categories[category].append(skill)
                categorized = True
                break
        
        if not categorized:
            categories["Other Skills"].append(skill)
    
    # Remove empty categories
    return {k: v for k, v in categories.items() if v}



def save_job_skills_to_database(skills: List[str], clear_existing: bool = True) -> Dict[str, any]:
    """Save extracted skills to the skill_category table."""
    try:
        print("=" * 50)
        print("SAVING SKILLS TO DATABASE")
        print("=" * 50)
        print(f"Skills to save: {skills}")
        print(f"Clear existing: {clear_existing}")
        print(f"Number of skills: {len(skills)}")
        
        env = load_env_vars()
        print(f"Environment loaded: {bool(env)}")
        
        conn = connect_postgres(env)
        print("Database connection established")
        
        cur = conn.cursor()
        
        deleted_count = 0
        added_count = 0
        duplicate_count = 0
        
        # Clear existing skills if requested
        if clear_existing:
            print("Clearing existing skills...")
            cur.execute("SELECT COUNT(*) FROM skill_category;")
            deleted_count = cur.fetchone()[0]
            print(f"Found {deleted_count} existing skills to delete")
            
            cur.execute("TRUNCATE TABLE skill_category RESTART IDENTITY CASCADE;")
            print("Existing skills cleared")
        
        # Insert new skills
        print("Inserting new skills...")
        for i, skill in enumerate(skills, 1):
            print(f"Processing skill {i}/{len(skills)}: '{skill}'")
            
            cur.execute("""
                INSERT INTO skill_category(name)
                VALUES (LOWER(%s))
                ON CONFLICT(name) DO NOTHING
                RETURNING name;
            """, (skill,))
            
            result = cur.fetchone()
            if result:
                added_count += 1
                print(f"  ✅ Added: {skill}")
            else:
                duplicate_count += 1
                print(f"  ⚠️ Duplicate (skipped): {skill}")
        
        conn.commit()
        print("Database changes committed")
        
        cur.close()
        conn.close()
        print("Database connection closed")
        
        final_result = {
            'success': True,
            'added_count': added_count,
            'duplicate_count': duplicate_count,
            'deleted_count': deleted_count
        }
        
        print("-" * 50)
        print("FINAL RESULT:")
        print(f"Success: {final_result['success']}")
        print(f"Added: {final_result['added_count']}")
        print(f"Duplicates: {final_result['duplicate_count']}")
        print(f"Deleted: {final_result['deleted_count']}")
        print("=" * 50)
        
        return final_result
        
    except Exception as e:
        error_msg = str(e)
        print("!" * 50)
        print("ERROR SAVING SKILLS:")
        print(f"Error: {error_msg}")
        print("!" * 50)
        
        return {
            'success': False,
            'error': error_msg,
            'added_count': 0,
            'duplicate_count': 0,
            'deleted_count': 0
        }