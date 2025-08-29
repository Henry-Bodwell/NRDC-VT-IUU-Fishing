import csv
from typing import List, Set, Dict
import math


def read_keywords_from_file(file_path: str) -> List[str]:
    """Read keywords from a text file, one per line."""
    keywords = []
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            for line in file:
                keyword = line.strip()
                if keyword and keyword != "Keyword":  # Skip header
                    keywords.append(keyword)
    except FileNotFoundError:
        print(f"File {file_path} not found. Using default keywords.")
    return keywords


def create_exclusive_fishing_queries(
    keywords: List[str], max_chars: int = 500
) -> List[str]:
    """
    Create exclusive search queries for illegal fishing activities.
    Each query will contain fish/seafood terms AND illegal/enforcement terms.
    """

    # Define required categories - must have at least one from each
    fish_seafood_terms = {
        "fish",
        "seafood",
        "unagi",
        "fishmeal",
        "pearls",
        "liver oil",
        "surimi",
        "swim bladder",
        "caviar",
        "shark fin",
        "gill raker",
    }

    illegal_enforcement_terms = {
        "IUU",
        "illegal",
        "fraud",
        "investigation",
        "enforcement",
        "arrest",
        "charges",
        "indicted",
        "violation",
        "falsify",
        "misrepresent",
        "evasion",
        "sanctions",
        "unauthorized",
        "unlicensed",
        "prohibited gear",
        "banned gear",
        "closed area",
        "closed season",
        "not permitted",
        "unreported",
        "underreport",
        "misreport",
        "unregistered",
        "unapproved",
    }

    # Filter available terms from input keywords
    available_fish_terms = [
        term for term in keywords if term.lower() in fish_seafood_terms
    ]
    available_illegal_terms = [
        term for term in keywords if term.lower() in illegal_enforcement_terms
    ]

    # Other terms for OR conditions
    other_terms = [
        term
        for term in keywords
        if term.lower() not in fish_seafood_terms
        and term.lower() not in illegal_enforcement_terms
    ]

    print(f"Fish/Seafood terms found: {len(available_fish_terms)}")
    print(f"Illegal/Enforcement terms found: {len(available_illegal_terms)}")
    print(f"Other terms: {len(other_terms)}")

    queries = []
    used_terms = set()

    # Calculate how many queries we need to distribute terms evenly
    total_terms = len(keywords)
    estimated_queries = math.ceil(total_terms / 15)  # Rough estimate

    # Create base combinations of fish + illegal terms
    base_combinations = []
    for fish_term in available_fish_terms:
        for illegal_term in available_illegal_terms:
            base_combinations.append((fish_term, illegal_term))

    # Distribute other terms across queries
    other_terms_chunks = []
    chunk_size = max(1, len(other_terms) // len(base_combinations))

    for i in range(0, len(other_terms), chunk_size):
        other_terms_chunks.append(other_terms[i : i + chunk_size])

    # Ensure we have enough chunks
    while len(other_terms_chunks) < len(base_combinations):
        other_terms_chunks.append([])

    # Create queries
    for i, (fish_term, illegal_term) in enumerate(base_combinations):
        if i >= len(other_terms_chunks):
            chunk = []
        else:
            chunk = other_terms_chunks[i]

        # Start with required terms
        base_query = f'"{fish_term}" AND "{illegal_term}"'
        current_length = len(base_query)

        # Add other terms that fit
        or_terms = []
        for term in chunk:
            test_addition = f' OR "{term}"'
            if (
                current_length + len(test_addition) < max_chars - 20
            ):  # Buffer for parentheses
                or_terms.append(f'"{term}"')
                current_length += len(test_addition)
                used_terms.add(term)

        # Construct final query
        if or_terms:
            or_part = " OR ".join(or_terms)
            query = f"({base_query}) AND ({or_part})"
        else:
            query = base_query

        if len(query) <= max_chars:
            queries.append(query)
            used_terms.add(fish_term)
            used_terms.add(illegal_term)

    # Handle any remaining unused terms
    unused_terms = [term for term in keywords if term not in used_terms]

    if unused_terms:
        # Create additional queries for remaining terms
        fish_default = available_fish_terms[0] if available_fish_terms else "fish"
        illegal_default = (
            available_illegal_terms[0] if available_illegal_terms else "illegal"
        )

        while unused_terms:
            base_query = f'"{fish_default}" AND "{illegal_default}"'
            current_length = len(base_query)

            or_terms = []
            terms_to_remove = []

            for term in unused_terms:
                test_addition = f' OR "{term}"'
                if current_length + len(test_addition) < max_chars - 20:
                    or_terms.append(f'"{term}"')
                    current_length += len(test_addition)
                    terms_to_remove.append(term)

            # Remove used terms
            for term in terms_to_remove:
                unused_terms.remove(term)

            # Create query
            if or_terms:
                or_part = " OR ".join(or_terms)
                query = f"({base_query}) AND ({or_part})"
                if len(query) <= max_chars:
                    queries.append(query)

            # Break if no progress made
            if not terms_to_remove:
                break

    return queries


def analyze_queries(queries: List[str]) -> Dict:
    """Analyze the generated queries for statistics."""
    stats = {
        "total_queries": len(queries),
        "max_length": max(len(q) for q in queries) if queries else 0,
        "min_length": min(len(q) for q in queries) if queries else 0,
        "avg_length": sum(len(q) for q in queries) / len(queries) if queries else 0,
        "over_limit": sum(1 for q in queries if len(q) > 500),
    }
    return stats


def save_queries_to_csv(
    queries: List[str], output_file: str = "exclusive_fishing_queries.csv"
):
    """Save the generated queries to a CSV file with metadata."""
    with open(output_file, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["Query_ID", "Query", "Length", "Valid"])

        for i, query in enumerate(queries, 1):
            is_valid = "✓" if len(query) <= 500 else "⚠"
            writer.writerow([f"Q{i:03d}", query, len(query), is_valid])

    print(f"Saved {len(queries)} queries to {output_file}")


# Main execution
if __name__ == "__main__":
    # Read keywords from your file
    keywords = read_keywords_from_file("Keyword.txt")

    if not keywords:
        print("No keywords found. Please check your file.")
        exit()

    print(f"Loaded {len(keywords)} keywords from file\n")

    # Generate exclusive queries
    queries = create_exclusive_fishing_queries(keywords, max_chars=500)

    # Analyze results
    stats = analyze_queries(queries)

    print(f"\n{'='*50}")
    print("QUERY GENERATION RESULTS")
    print(f"{'='*50}")
    print(f"Total queries generated: {stats['total_queries']}")
    print(f"Maximum query length: {stats['max_length']} characters")
    print(f"Minimum query length: {stats['min_length']} characters")
    print(f"Average query length: {stats['avg_length']:.1f} characters")
    print(f"Queries over 500 chars: {stats['over_limit']}")
    print(f"{'='*50}\n")

    # Display first few queries as examples
    print("SAMPLE QUERIES:")
    print("-" * 50)
    for i, query in enumerate(queries[:3], 1):
        print(f"Query {i} ({len(query)} chars):")
        print(f"{query}\n")

    if len(queries) > 3:
        print(f"... and {len(queries) - 3} more queries")

    # Save to CSV
    save_queries_to_csv(queries)

    # Validation
    if stats["over_limit"] == 0:
        print("✓ All queries are under 500 characters!")
    else:
        print(f"⚠ {stats['over_limit']} queries exceed 500 characters")

    print(f"\nQueries ensure each result will contain:")
    print("- At least one fish/seafood term (fish, seafood, unagi, etc.)")
    print("- At least one illegal/enforcement term (illegal, fraud, violation, etc.)")
    print("- Various other relevant terms as OR conditions")
