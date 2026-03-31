import pandas as pd
import os

# ============================================================
# CONFIG
# ============================================================
SOURCE_FILE = "contacts_with_linkedin.xlsx"
TARGET_FILE = "Sample linkedin contacts to extract.xlsx"
OUTPUT_FILE = "Sample_linkedin_contacts_UPDATED.xlsx"

# ============================================================
# MERGE LOGIC
# ============================================================
def merge_results():
    if not os.path.exists(SOURCE_FILE):
        print(f"Error: {SOURCE_FILE} not found.")
        return
    if not os.path.exists(TARGET_FILE):
        print(f"Error: {TARGET_FILE} not found.")
        return

    print(f"Loading files...")
    df_source = pd.read_excel(SOURCE_FILE)
    df_target = pd.read_excel(TARGET_FILE)
    
    # We only want to keep the valuable columns from the source
    # Such as those that are NOT_FOUND or found via API
    source_cols = ['Record ID', 'Contact LinkedIn URL', 'LinkedIn Score', 'LinkedIn Confidence']
    df_source_subset = df_source[source_cols]
    
    print(f"Target count: {len(df_target)}")
    
    # Perform the merge based on 'Record ID'
    # Use a left join to keep all target rows
    # We remove the target's existing LinkedIn columns to replace them with the merged ones
    df_target_clean = df_target.drop(columns=['Contact LinkedIn URL', 'LinkedIn Score', 'LinkedIn Confidence'], errors='ignore')
    
    # To keep the order and existence of columns in the target, we do a left merge
    df_merged = pd.merge(df_target_clean, df_source_subset, on='Record ID', how='left')
    
    # Ensure correct column ordering for the target
    final_cols = ['Record ID', 'Contact Name', 'Contact Email', 'Company name', 'Industry', 'City', 'Country/Region', 'Contact LinkedIn URL', 'LinkedIn Score', 'LinkedIn Confidence', 'LinkedIn Search Link']
    
    # Make sure all columns exist
    for col in final_cols:
        if col not in df_merged.columns:
            df_merged[col] = ""
            
    df_merged = df_merged[final_cols]
    
    print(f"Final Count: {len(df_merged)}")
    
    # Save the result
    df_merged.to_excel(OUTPUT_FILE, index=False)
    print(f"Successfully saved merged results to: {OUTPUT_FILE}")

if __name__ == "__main__":
    merge_results()
