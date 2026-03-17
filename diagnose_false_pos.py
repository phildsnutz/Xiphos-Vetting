import sys
sys.path.insert(0, "/app/backend")

from ofac import screen_name, jaro_winkler, get_active_db

# Check which DB is active
db, label = get_active_db()
sys.stdout.write("Active DB: " + label + "\n")

# Screen the two false-positive entities
for vendor in ["BAE Systems", "Samsung Electronics"]:
    result = screen_name(vendor, threshold=0.70)  # Lower threshold to see what's matching
    sys.stdout.write("\n--- {} ---\n".format(vendor))
    sys.stdout.write("  matched: {} | best_score: {:.4f}\n".format(result.matched, result.best_score))
    if result.matched_entry:
        sys.stdout.write("  matched_entry: {} ({})\n".format(result.matched_entry.name, result.matched_entry.country))
        sys.stdout.write("  matched_name: {}\n".format(result.matched_name))
    sys.stdout.write("  all_matches ({}):\n".format(len(result.all_matches)))
    for m in result.all_matches[:10]:
        sys.stdout.write("    {:.4f} | {} -> {} ({})\n".format(
            m.score, m.matched_on, m.entry.name, m.entry.country))

# Also manually check Jaro-Winkler against fallback entries
sys.stdout.write("\n\n--- MANUAL JW SCORES ---\n")
for vendor in ["BAE Systems", "Samsung Electronics"]:
    sys.stdout.write("\n{} vs fallback:\n".format(vendor))
    for entry in db[:20]:  # First 20 entries
        names = [entry.name] + entry.aliases
        for name in names:
            score = jaro_winkler(vendor, name)
            if score > 0.50:
                sys.stdout.write("  {:.4f} | {} vs {}\n".format(score, vendor, name))

sys.stdout.flush()
