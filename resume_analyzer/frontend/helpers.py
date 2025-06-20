from typing import List, Dict, Optional, Tuple
import psycopg2
from ..ingestion.helpers import connect_postgres, load_env_vars

from typing import Dict, List, Tuple, Optional
import streamlit as st
from .helpers import connect_postgres, load_env_vars

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

def delete_candidate_records(candidate_key: str) -> Dict[str, int]:
    """
    Delete all records for a specific candidate from both tables.
    
    Args:
        candidate_key: The candidate identifier to delete
        
    Returns:
        Dictionary with deletion counts from both tables
    """
    try:
        env = load_env_vars()
        conn = connect_postgres(env)
        cur = conn.cursor()
        
        # Delete from resumes_metadata
        cur.execute("""
            DELETE FROM public.resumes_metadata 
            WHERE candidate_key = %s;
        """, (candidate_key,))
        metadata_deleted = cur.rowcount
        
        # Delete from resumes_normal
        cur.execute("""
            DELETE FROM public.resumes_normal 
            WHERE candidate_key = %s;
        """, (candidate_key,))
        normal_deleted = cur.rowcount
        
        conn.commit()
        cur.close()
        conn.close()
        
        return {
            'metadata_deleted': metadata_deleted,
            'normal_deleted': normal_deleted,
            'total_deleted': metadata_deleted + normal_deleted
        }
        
    except Exception as e:
        st.error(f"Error deleting candidate records: {e}")
        return {'metadata_deleted': 0, 'normal_deleted': 0, 'total_deleted': 0}

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