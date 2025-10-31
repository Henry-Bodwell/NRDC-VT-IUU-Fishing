# FIRST, DO THE FOLLOWING MANUAL CLEANING STEPS OF THE XLSX DATA FILE
# Create concise names for KDEs and behaviors 
# Only keep Behavior Category, Behavior, and KDE columns (Delete all other columns)
# Only keep abbreviated KDEs and KDE Grouping rows (Delete CTE, who/what/when, and full KDE name rows)
# Remove crossed-out rows (e.g, "Failure by flag state to exercise effective control)

rm(list=ls())
# Load required libraries
library(tidyverse)
library(pheatmap)
library(FactoMineR)
library(factoextra)
library(corrplot)
library(dendextend)

# Define target directory
target_dir <- "clusterKDEs"
# Use getwd() to retrieve the current directory path
current_wd <- getwd()

if (basename(current_wd) != target_dir) {
  # Construct the full path using file.path()
  new_path <- current_wd %>%
    file.path(target_dir)
  # Change the Working Directory
  # Note: assumes the 'clusterKDEs' directory already exists within current_wd.
  setwd(new_path)
}

#raw_data <- read_csv(file = "Clustering Data Viz.csv", name_repair = "minimal")

raw_data <- read_csv(file = "Clustering Data Viz.csv")

header_row1 <- raw_data[1, ] # kde groups
header_row2 <- colnames(raw_data) # kde labels

# Convert the unique character strings in header_row1 to numeric IDs.
# Select all columns except the first two
numeric_ids <- header_row1 %>%
  select(-c(1,2)) %>%
  # Transpose and convert to a vector of characters
  unlist() %>%
  # Convert character values to factors, then to numeric IDs
  as.factor() %>%
  as.numeric()

kde_group <- header_row1 %>%
  select(-c(1,2)) %>%
  # Transpose and convert to a vector of characters
  unlist()  %>%
  as.character()

# Create a dataframe (LEGEND) that maps numeric_ids to kde_groups
kde_legend <- data.frame(
  numeric_id = numeric_ids,
  kde_group = kde_group) %>%
  distinct() %>%
  arrange(numeric_id)

# Combine the numeric IDs with the KDE labels (Vessel name, UVI number, ...).
# Use columns 3 to last for the KDE labels as well.
kde_labels <- header_row2[3:length(header_row2)] %>% unlist()
new_col_names <- map2_chr(
  numeric_ids,
  kde_labels,
  ~ paste0(.x, ": ", .y) # Combines, e.g., '1' and 'Vessel name' to '1: Vessel name'
)

# Create the final data frame
data_with_new_header <- raw_data %>%
  # Remove the first row (KDE groups)
  slice(-1) %>%
  # Create new first column combining behavior category and behavior (e.g, I: exceeding catch quotas)
  mutate(
    # Combine the first two columns into a new Behavior identifier
    Behavior = paste0(`Behavior category`, ": ", Behavior),
    # Ensure this new column is created for the remaining data rows
    .before = 1
  ) %>%
  # Drop the behavior category column
  select(-1) %>%
  # Split the data columns from the Behavior column for safe renaming
  select(Behavior) %>% # Keep the new combined Behavior column
  bind_cols(
    raw_data %>%
      slice(-1) %>% # Match the slice operation above
      select(-c(1, 2)) %>% # Select only the data columns
      #slice(-1) %>% # Remove the remaining header row
      # Apply the new combined names to the data columns
      set_names(new_col_names)
  ) %>%
  # Ensure all data columns (now columns 2 and onwards) are numeric
  mutate(across(2:last_col(), as.numeric))

# Clean and convert dataframe to matrix
data_matrix <- data_with_new_header %>%
  # Selects columns where NOT all values in that column are NA.
  # i.e., remove any unused KDEs like "Coastal entry and exit"
  select(where(~ !all(is.na(.)))) %>%
  # Convert NAs to 0s
  mutate(across(-Behavior, replace_na, 0)) %>%
  # set row names
  column_to_rownames(var = "Behavior") %>%
  # Final conversion to matrix for downstream analysis
  as.matrix()