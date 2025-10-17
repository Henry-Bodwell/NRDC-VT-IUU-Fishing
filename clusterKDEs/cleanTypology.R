# MANUAL STEPS:
# FIRST, manually remove first two rows and columns 2 and 3 so that CSV is just the column and row names and data

#### TO DO: need to RE-EXPORT CSV (now with clean behavior descriptions)


rm(list=ls())

# Load required libraries
library(tidyverse)
library(pheatmap)
library(FactoMineR)
library(factoextra)
library(corrplot)

# LOAD, CLEAN, and REORDER DATA:
raw_data <- read_csv(file = "Database of IUU+ behaviors - CLEAN VERSION - IUU+ Behaviors and KDEs.csv")

# Check full data loaded:
colnames(raw_data) # Last column: sanitary license ID
raw_data[nrow(raw_data),] # Last row: Stolen products

# Convert the first column to row names and convert to matrix
data_matrix <- raw_data %>%
  # Tidyverse way to ensure the data columns (now column 2 through the end) are numeric
  mutate(across(2:last_col(), as.numeric)) %>%
  # Tidyverse way to set row names
  column_to_rownames(var = "Behavior") %>%
  # Base R: Final conversion to matrix for downstream analysis
  as.matrix()

# Convert to data frame, filter out rows that are just NAs (these are the behavior categories), then convert back to matrix
data_matrix <- data_matrix %>%
  as.data.frame() %>%
  # We must first temporarily save the row names back as a column to filter properly
  rownames_to_column(var = "Behavior_Name_Temp") %>%
  # Filter: keep rows where NOT (all data columns are NA).
  # Data columns are now columns 2 through the end of this temporary data frame.
  filter(!if_all(2:last_col(), is.na)) %>%
  column_to_rownames(var = "Behavior_Name_Temp") %>%
  as.matrix()

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
custom_colors <- c("white", "#FED976", "#FD8D3C") # White (0), Light Orange (1), Dark Orange (2)
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
cat("\nClustered Heatmap generated and saved as 'clustered_heatmap.png'\n")

# DATA VIZ 2: Correlation Matrices and Hierarchical Clustering ---
# This method first quantifies the similarity between pairs of variables.
# We use Spearman's rank correlation (rho) because your data (0, 1, 2) is ordinal.

# 3a. KDE Correlation Matrix (90x90): Relationship between KDEs

# Calculate correlation between KDEs (columns)
kde_corr <- cor(data_matrix, method = "spearman")

# Visualize the KDE correlation matrix
corrplot(kde_corr,
         method = "color",
         type = "upper",
         order = "hclust", # Use hierarchical clustering to reorder
         tl.cex = 0.4, # Adjust label size
         title = "Spearman Correlation (KDEs)",
         mar = c(0, 0, 1, 0)
)
cat("KDE Correlation plot displayed (Correlation between KDEs).\n")
# To save: png("kde_correlation.png", width = 800, height = 800); corrplot(...); dev.off()


# 3b. Behavior Correlation Matrix (68x68): Relationship between Behaviors

# Calculate correlation between Behaviors (rows)
behavior_corr <- cor(t(data_matrix), method = "spearman")

# Visualize the Behavior correlation matrix
corrplot(behavior_corr,
         method = "color",
         type = "upper",
         order = "hclust", # Use hierarchical clustering to reorder
         tl.cex = 0.5,
         title = "Spearman Correlation (Behaviors)",
         mar = c(0, 0, 1, 0)
)
cat("Behavior Correlation plot displayed (Correlation between Behaviors).\n")
# To save: png("behavior_correlation.png", width = 800, height = 800); corrplot(...); dev.off()


## DATA VIZ 3: Correspondence Analysis (CA) Biplot ---

# CA is designed for two-way categorical/count tables to visualize row and column
# associations simultaneously in a low-dimensional space.

# 4a. Run Correspondence Analysis
# Since CA is typically for counts, we treat the ordinal scores (0, 1, 2) as
# indicators of different levels of association/frequency.
ca_result <- CA(data_matrix, graph = FALSE)

# 4b. Visualize the Biplot
# The biplot shows both behaviors (rows) and KDEs (columns) on the same plot.
# Points close to each other are strongly associated.
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
cat("Correspondence Analysis Biplot displayed (Shows simultaneous association).\n")