# FIRST, DO THE FOLLOWING MANUAL CLEANING STEPS OF THE XLSX DATA FILE
# Create concise names for KDEs and behaviors 
# Remove first two rows and first three columns
# Label new first column as "Behavior"
# Remove crossed-out rows (e.g, "Failure by flag state to exercise effective control)
rm(list=ls())

# Load required libraries
library(tidyverse)
library(pheatmap)
library(FactoMineR)
library(factoextra)
library(corrplot)
library(gridExtra) # for combining plot and table legend


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

# Load, clean, and reorder data:
raw_data <- read_csv(file = "Database of IUU+ behaviors - CLEAN VERSION - IUU+ Behaviors and KDEs.csv")

# Check full data loaded:
colnames(raw_data) # Last column: sanitary license ID
raw_data[nrow(raw_data),] # Last row: Stolen products

data_matrix <- raw_data %>%
  # Step 1: Ensure columns are numeric for calculation/matrix conversion
  mutate(across(2:last_col(), as.numeric)) %>%
  # Keeps rows where at least one column (excluding 'Behavior') is NOT NA.
  # i.e., filter out header rows like "Illegal fishing"
  filter(if_any(-Behavior, ~ !is.na(.))) %>%
  # Selects columns where NOT all values in that column are NA.
  # i.e., remove any unused KDEs like "Coastal entry and exit" 
  select(where(~ !all(is.na(.)))) %>%
  # set row names
  column_to_rownames(var = "Behavior") %>%
  # Final conversion to matrix for downstream analysis
  as.matrix()


# Convert to data frame, filter out rows that are just NAs (these are the behavior categories), then convert back to matrix
# data_matrix <- data_matrix %>%
#   as.data.frame() %>%
#   # We must first temporarily save the row names back as a column to filter properly
#   rownames_to_column(var = "Behavior_Name_Temp") %>%
#   # Filter: keep rows where NOT (all data columns are NA).
#   # Data columns are now columns 2 through the end of this temporary data frame.
#   filter(!if_all(2:last_col(), is.na)) %>%
#   column_to_rownames(var = "Behavior_Name_Temp") %>%
#   as.matrix()

# Re-map the ordinal values to reflect the desired ordered values: 
# Current order: 0 == No relationship between KDE and behavior | 1 == Direct relationship | 2 == Indirect relationship
# Desired order:  0 == No relationship between KDE and behavior | 1 == Indirect relationship | 2 == Direct relationship
temp_matrix <- data_matrix
# Swap 1s (Direct) with 99 (temporary value)
temp_matrix[data_matrix == 1] <- 99
# Swap 2s (Indirect) with 1
temp_matrix[data_matrix == 2] <- 1
# Swap 99s (Direct) with 2
temp_matrix[temp_matrix == 99] <- 2
data_matrix <- temp_matrix
# Replace NA values (originally blank in the raw data) with 0
data_matrix[is.na(data_matrix)] <- 0




## DATA VIZ 1: Clustered Heatmap

# Define custom colors for 0, 1, and 2
custom_colors <- c("white", "gold", "orange") # White (0), Gold (1), Orange (2)
names(custom_colors) <- c("0", "1", "2")

# Generate the heatmap.
# Clustering method "complete" and distance "euclidean" are standard defaults,
# but can be changed (e.g., to "manhattan" for ordinal data).
pheatmap(
  data_matrix,
  color = unlist(custom_colors),
  breaks = c(-0.5, 0.5, 1.5, 2.5), # Define breaks for 0, 1, and 2
  clustering_method = "complete",
  main = "Clustered Heatmap of KDE-Behavior Relevance (0, 1=Indirect, 2=Direct)",
  fontsize_row = 7,
  fontsize_col = 7,
  filename = "clustered_heatmap.png",
  width = 12,
  height = 10
)

# DATA VIZ 2: Correlation Matrices and Hierarchical Clustering ---
# Use Spearman's rank correlation because data is ordered (0, 1, 2).

# KDE Correlation Matrix: Relationship between KDEs

# Calculate correlation between KDEs (columns)
kde_corr <- cor(data_matrix, method = "spearman")

# Visualize the KDE correlation matrix
png("kde_correlation.png", width = 3000, height = 3000, res = 300)
corrplot(kde_corr,
         method = "color",
         type = "upper",
         order = "hclust", # Use hierarchical clustering to reorder
         tl.cex = 0.4, # Adjust label size
         title = "Spearman Correlation (KDEs)",
         mar = c(0, 0, 1, 0))
dev.off()


# Behavior Correlation Matrix: Relationship between Behaviors

# Calculate correlation between Behaviors (rows)
behavior_corr <- cor(t(data_matrix), method = "spearman")

# Visualize the Behavior correlation matrix
png("behavior_correlation.png", width = 3000, height = 3000, res = 300)
corrplot(behavior_corr,
         method = "color",
         type = "upper",
         order = "hclust", # Use hierarchical clustering to reorder
         tl.cex = 0.5,
         title = "Spearman Correlation (Behaviors)",
         mar = c(0, 0, 1, 0))
dev.off()


## DATA VIZ 3: Correspondence Analysis (CA) Biplot ---

#### FIX IT: What's the difference between map = "colgreen" and "rowgreen"

# CA is for two-way categorical/count tables to visualize row and column associations simultaneously in a low-dimensional space.

# 4a. Run Correspondence Analysis
# CA is typically for counts, but here we treat the ordinal scores (0, 1, 2) as indicators of different levels of association/frequency.
ca_result <- CA(data_matrix, graph = FALSE)

png("CA_biplot.png", width = 3000, height = 3000, res = 300)
fviz_ca_biplot(ca_result,
               repel = TRUE, # Avoid text overlap
               title = "Correspondence Analysis (CA) Biplot",
               map = "colgreen", # Change map to 'rowgreen' to focus on behaviors
               arrow = c(FALSE, TRUE), # Show KDEs as arrows, Behaviors as points
               col.row = "darkblue",
               col.col = "darkorange",
               geom = c("point", "text"),
               legend.title = list(row = "Behaviors", col = "KDEs")
)
dev.off()


# FIX IT: Loop through data matrix to do CA for groups of sub-behaviors

# Illegal fishing
data_behavior_group <- data_matrix[1:5,]
data_behavior_group <- data_behavior_group[,colSums(data_behavior_group != 0) > 0] # Illegal fishing

# Create KDE-to-Number Mapping for Cleaner Plot Labels
original_kde_names <- colnames(data_behavior_group)
kde_legend <- tibble(
  Number = 1:length(original_kde_names),
  KDE_Name = original_kde_names
)

# Rename the columns in the matrix to use numbers as labels
colnames(data_behavior_group) <- as.character(kde_legend$Number)

# Perform Correspondence Analysis - same as analysis above performed on full dataset
ca_result <- CA(data_behavior_group, graph = FALSE)

# Plot
# Save the biplot as a ggplot object
biplot_p <- fviz_ca_biplot(ca_result,
                           repel = TRUE, # Avoid text overlap
                           title = "", # Remove individual title as we use an overall title for grid.arrange
                           map = "colgreen",
                           arrow = c(FALSE, TRUE),
                           col.row = "darkblue",
                           col.col = "darkorange",
                           geom = c("point", "text"),
                           legend.title = list(row = "Behaviors", col = "KDE Numbers")
)

# Make the plot legend using the kde_legend data frame; use base_size to adjust font
legend_table <- tableGrob(kde_legend, rows = NULL, theme = ttheme_default(base_size = 8))

# Set up the PNG device for high-resolution output
png("CA_biplot.png", width = 4000, height = 2200, res = 300)

# Arrange the biplot and the legend table side-by-side (ncol=2)
grid.arrange(
  biplot_p,
  legend_table,
  ncol = 2, # Changed to 2 to place them in columns
  widths = c(3, 1), # Allocates 3/4 of horizontal space to the plot and 1/4 to the table
  top = "Correspondence Analysis (CA) Biplot (KDEs labeled by Number)" # Overall title
)

dev.off()
