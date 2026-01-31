# Run below on data matrix with aquaculture data
# FIX IT - combine clusterData and clusterData-noAquaculture (add dynamic filenaming, etc)

#########################################################################################
# DATA VIZ 1: Correlation Matrices and Hierarchical Clustering
# Use Spearman's rank correlation because data is ordered (0, 1, 2)

# Calculate correlation between all pairs of KDEs (columns)
kde_corr <- cor(data_matrix, method = "spearman")
# Resulting matrix: position i,j shows the correlation coefficient between column i and column j of data_matrix

# Visualize the KDE correlation matrix
png("correlation_matrix_kdes.png", width = 3000, height = 3000, res = 300)
corrplot(kde_corr,
         method = "color",
         type = "upper",
         order = "hclust", # Use hierarchical clustering to reorder
         hclust.method = "ward.D2",
         tl.cex = 0.4, # Adjust label size
         title = "Spearman Correlation (KDEs)",
         mar = c(0, 0, 1, 0))
dev.off()

# Calculate correlation between all pairs of Behaviors (rows)
behavior_corr <- cor(t(data_matrix), method = "spearman")
# Resulting matrix: position i,j shows the correlation coefficient between row i and column j of data_matrix

# Visualize the Behavior correlation matrix
png("correlation_matrix_behaviors.png", width = 3000, height = 3000, res = 300)
corrplot(behavior_corr,
         method = "color",
         type = "upper",
         order = "hclust", # Use hierarchical clustering to reorder
         hclust.method = "ward.D2",
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
  filename = "clustered_heatmap.png",
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
png("dendrogram_behaviors.png", width = 2000, height = 4000, res = 300)

# Adjust plot margins: mar = c(bottom, left, top, right)
# Increase the bottom margin (mar[1]) significantly to make space for labels.
par(mar = c(5, 4, 4, 15) + 0.1)

# Plot the final customized dendrogram
plot(
  dend,
  horiz = TRUE, # plot dendrogram horizontally
  main = "Hierarchical Clustering of Behaviors",
  xlab = "Manhattan Distance (Ward Linkage)",
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
  color_branches(k = 6, col = c("red", "blue", "green3", "purple", "orange", "cyan")) %>%
  set("labels_cex", 1) %>%      # Set label font size
  set("branches_lwd", 2) %>%      # Use "branches_lwd" to set line thickness
  set("hang_leaves")              # Ensure all labels hang at the bottom

# Set PNG device for high-resolution output
#png("CA_biplot.png", width = 4000, height = 2200, res = 300)

png("dendrogram_kdes.png", width = 2000, height = 4000, res = 300)
#png("behavior_dendrogram_dendextend.png", width = 1000, height = 800)

# Adjust plot margins: mar = c(bottom, left, top, right)
# Increase the bottom margin (mar[1]) significantly to make space for labels.
par(mar = c(5, 4, 4, 15) + 0.1)

# Plot the final customized dendrogram
plot(
  dend,
  horiz = TRUE, # plot dendrogram horizontally
  main = "Hierarchical Clustering of KDEs",
  xlab = "Manhattan Distance (Ward Linkage)",
  cex.main = 1.2, # Increase plot title size
  cex.lab = 1.2,  # Increase axis label size (for xlab and ylab)
  cex.axis = 1.2  # Increase axis tick mark number size
)

dev.off(); par(mar = c(5, 4, 4, 2) + 0.1)
