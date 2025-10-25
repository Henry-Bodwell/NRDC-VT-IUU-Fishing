# FIRST, DO THE FOLLOWING MANUAL CLEANING STEPS OF THE XLSX DATA FILE
# Create concise names for KDEs and behaviors 
# Remove first three rows and first three columns
# Label new first column as "Behavior"
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

# Use this block if removing aquaculture KDEs (part of block of code below) and behaviors (second block of code below)
raw_data <- read_csv(file = "Clustering Data Viz.csv")
# Clean and convert dataframe to matrix
df <- raw_data %>%
  # Mutate columns to numeric for calculation/matrix conversion
  mutate(across(2:last_col(), as.numeric)) %>%
  # Keeps rows where at least one column (excluding 'Behavior') is NOT NA.
  # i.e., filter out header rows like "Illegal fishing"
  filter(if_any(-Behavior, ~ !is.na(.))) %>%
  # Selects columns where NOT all values in that column are NA.
  # i.e., remove any unused KDEs like "Coastal entry and exit"
  select(where(~ !all(is.na(.)))) %>%
  # Remove all KDEs that are specific to aquaculture
  select(!contains("Aqua")) %>%
  # Convert to a tibble with row index to find position
  rowid_to_column(var = "row_index")

# Find the row index (row number) of the first instance containing "farmed" - the first row for illegal Aquaculture
target_index <- df %>%
  filter(str_detect(Behavior, "farmed")) %>%
  slice(1) %>%
  pull(row_index)

# Remove the target row and all subsequent rows
data_matrix <- df %>%
  filter(row_index < target_index) %>%
  # set row names
  column_to_rownames(var = "Behavior") %>%
  select(-row_index) %>%
  # Final conversion to matrix for downstream analysis
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
#########################################################################################
# DATA VIZ 1: Correlation Matrices and Hierarchical Clustering
# Use Spearman's rank correlation because data is ordered (0, 1, 2)

# Calculate correlation between all pairs of KDEs (columns)
kde_corr <- cor(data_matrix, method = "spearman")
# Resulting matrix: position i,j shows the correlation coefficient between column i and column j of data_matrix

# Visualize the KDE correlation matrix
png("correlation_matrix_kdes_no-Aquaculture.png", width = 3000, height = 3000, res = 300)
corrplot(kde_corr,
         method = "color",
         type = "upper",
         order = "hclust", # Use hierarchical clustering to reorder
         tl.cex = 0.4, # Adjust label size
         title = "Spearman Correlation (KDEs)",
         mar = c(0, 0, 1, 0))
dev.off()

# Calculate correlation between all pairs of Behaviors (rows)
behavior_corr <- cor(t(data_matrix), method = "spearman")
# Resulting matrix: position i,j shows the correlation coefficient between row i and column j of data_matrix

# Visualize the Behavior correlation matrix
png("correlation_matrix_behaviors_no-Aquaculture.png", width = 3000, height = 3000, res = 300)
corrplot(behavior_corr,
         method = "color",
         type = "upper",
         order = "hclust", # Use hierarchical clustering to reorder
         tl.cex = 0.5,
         title = "Spearman Correlation (Behaviors)",
         mar = c(0, 0, 1, 0))
dev.off()
##########################################################################################
## DATA VIZ 2: Clustered Heatmap with dendogram

# Define custom colors for 0, 1, and 2
custom_colors <- c("grey95", "gold", "orange") # White (0), Gold (1), Orange (2)
names(custom_colors) <- c("0", "1", "2")

# NOTE: lots of other heatmap function - e.g., (1) plotly in combination with heatmap(), (2) d3heatmap, and (3) heatmaply
# Using pheatmap for easier high-level labeling of behaviors and KDEs using annotation_row and annotation_col 
pheatmap(
  data_matrix,
  color = unlist(custom_colors),
  breaks = c(-0.5, 0.5, 1.5, 2.5), # Non-continuous data, so need to define colors and breaks for 0, 1, and 2
  clustering_method = "ward.D2", # Uses Ward's Minimum Variance Method; minimizes within-cluster variance to create tight clusters and more appropriate for ordinal data
  # in contrast, clustering_method = "complete" minimizes the distance between the farthest points within a cluster
  main = "Clustered Heatmap of KDEs and Behaviors",
  cluster_rows = TRUE, # group similar illegal fishing behaviors together
  cluster_cols = TRUE, # group KDEs that share similar relationship patterns across all behaviors
  clustering_distance_rows = "manhattan", # appropriate for ordinal data; distance measured as steps on a grid as opposed to shortest distance (Euclidean)
  clustering_distance_cols = "manhattan",
  legend_breaks = c(0,1,2), # legend should show three distinct values and labels
  legend_labels = c("None", "Direct", "Indirect"), 
  fontsize_row = 7,
  fontsize_col = 7,
  filename = "clustered_heatmap_no-Aquaculture.png",
  width = 12,
  height = 10
)

##########################################################################################
# DATA VIZ 3: Zoom in on the Dendogram

# First create dendogram of behaviors
# Calculate distance using the Manhattan metric - 
# Manhattan is appropriate for ordinal data; distance measured as steps on a grid as opposed to shortest distance (Euclidean)
dist_matrix <- dist(data_matrix, method = "manhattan")

# Use Ward's Minimum Variance Method; minimizes within-cluster variance to create tight clusters and more appropriate for ordinal data
hclust_result <- hclust(dist_matrix, method = "ward.D2")

# Visualize dendrogram using dendextend

# Convert the hclust object to a dendrogram object
dend <- as.dendrogram(hclust_result)

# Color the branches based on 4 clusters
dend <- dend %>%
  color_branches(k = 4, col = c("darkred", "orange", "purple", "darkgreen")) %>%
  set("labels_cex", 1) %>%      # Set label font size
  set("branches_lwd", 2) %>%               # Set line width to 2
  set("hang_leaves")              # Ensure all labels hang at the bottom

# Set PNG device for high-resolution output
png("dendrogram_behaviors_no-Aquaculture.png", width = 2000, height = 4000, res = 300)

# Adjust plot margins: mar = c(bottom, left, top, right)
# Increase the bottom margin (mar[1]) significantly to make space for labels.
par(mar = c(5, 4, 4, 15) + 0.1)

# Plot the final customized dendrogram
plot(
  dend,
  horiz = TRUE, # plot dendrogram horizontally
  main = "Hierarchical Clustering of Behaviors",
  ylab = "Manhattan Distance (Ward Linkage)",
  cex.main = 1.2, # Increase plot title size
  cex.lab = 1.2,  # Increase axis label size (for xlab and ylab)
  cex.axis = 1.2  # Increase axis tick mark number size
)

dev.off(); par(mar = c(5, 4, 4, 2) + 0.1)
# Reset margins to default after plotting if you plan other plots in the same session

# Next create dendogram of KDEs - i.e., pass transposed matrix into dist function
# Calculate distance using the Manhattan metric - 
# Manhattan is appropriate for ordinal data; distance measured as steps on a grid as opposed to shortest distance (Euclidean)
dist_matrix <- dist(t(data_matrix), method = "manhattan")

# Use Ward's Minimum Variance Method; minimizes within-cluster variance to create tight clusters and more appropriate for ordinal data
hclust_result <- hclust(dist_matrix, method = "ward.D2")

# Visualize dendrogram using dendextend
# Convert the hclust object to a dendrogram object
dend <- as.dendrogram(hclust_result)

# Remove hashtags below to see color options
#c("red", "blue", "green3", "purple", "orange", "cyan") # vivid
#c("pink", "skyblue", "lightgreen", "mediumpurple", "gold", "tan") # darker saturated
#c("firebrick", "dodgerblue4", "forestgreen", "darkorchid4", "goldenrod", "saddlebrown") # pastel

# Color the branches based on 6 clusters
dend <- dend %>%
  color_branches(k = 5, col = c("red", "blue", "green3", "purple", "orange")) %>%
  set("labels_cex", 1) %>%      # Set label font size
  set("branches_lwd", 2) %>%      # Use "branches_lwd" to set line thickness
  set("hang_leaves")              # Ensure all labels hang at the bottom

# Set PNG device for high-resolution output
#png("CA_biplot.png", width = 4000, height = 2200, res = 300)

png("dendrogram_kdes_no-Aquaculture.png", width = 2000, height = 4000, res = 300)
#png("behavior_dendrogram_dendextend.png", width = 1000, height = 800)

# Adjust plot margins: mar = c(bottom, left, top, right)
# Increase the bottom margin (mar[1]) significantly to make space for labels.
par(mar = c(5, 4, 4, 15) + 0.1)

# Plot the final customized dendrogram
plot(
  dend,
  horiz = TRUE, # plot dendrogram horizontally
  main = "Hierarchical Clustering of KDEs",
  ylab = "Manhattan Distance (Ward Linkage)",
  cex.main = 1.2, # Increase plot title size
  cex.lab = 1.2,  # Increase axis label size (for xlab and ylab)
  cex.axis = 1.2  # Increase axis tick mark number size
)

dev.off(); par(mar = c(5, 4, 4, 2) + 0.1)

##############################################################################
## CODE BELOW DISCONTINUED FOR NOW
## DATA VIZ XX: Correspondence Analysis (CA) Biplot ---

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
