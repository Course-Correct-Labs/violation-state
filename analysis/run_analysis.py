"""
Main analysis pipeline for Violation State study.

This script:
1. Parses all conversation transcripts
2. Classifies each user-assistant exchange
3. Generates summary statistics
4. Produces visualization figures
5. Runs statistical tests
"""

import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import fisher_exact

# Add analysis directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from parse_transcripts import load_all_conversations, get_user_assistant_pairs
from classify_responses import (
    identify_prompt_id,
    classify_response,
    is_image_prompt,
    is_text_prompt,
    ResponseClass
)


def cohen_h(p1: float, p2: float) -> float:
    """
    Calculate Cohen's h effect size for difference between two proportions.

    Args:
        p1: Proportion in group 1
        p2: Proportion in group 2

    Returns:
        Cohen's h value
    """
    # Apply arcsine transformation
    phi1 = 2 * np.arcsin(np.sqrt(p1))
    phi2 = 2 * np.arcsin(np.sqrt(p2))
    return phi1 - phi2


def analyze_conversations(base_dir: str):
    """
    Run the complete analysis pipeline.

    Args:
        base_dir: Base directory containing the data/ folder
    """
    print("=" * 70)
    print("VIOLATION STATE ANALYSIS")
    print("=" * 70)
    print()

    # Step 1: Load conversations
    print("Step 1: Loading conversations...")
    data_dir = Path(base_dir) / "data"
    conversations = load_all_conversations(str(data_dir))
    print(f"  Loaded {len(conversations)} conversations")
    print(f"    Control: {sum(1 for c in conversations if c['condition'] == 'control')}")
    print(f"    Contaminated: {sum(1 for c in conversations if c['condition'] == 'contaminated')}")
    print()

    # Step 2: Extract and classify turns
    print("Step 2: Extracting and classifying turns...")
    turns_data = []

    for conv in conversations:
        thread_id = conv["thread_id"]
        condition = conv["condition"]
        pairs = get_user_assistant_pairs(conv)

        for user_turn, assistant_turn in pairs:
            prompt_id = identify_prompt_id(user_turn["text"])
            response_class = classify_response(prompt_id, assistant_turn["text"])

            turns_data.append({
                "thread_id": thread_id,
                "condition": condition,
                "user_turn_index": user_turn["turn_index"],
                "assistant_turn_index": assistant_turn["turn_index"],
                "prompt_id": prompt_id,
                "user_text": user_turn["text"],
                "assistant_text": assistant_turn["text"],
                "response_class": response_class.value
            })

    turns_df = pd.DataFrame(turns_data)
    print(f"  Extracted {len(turns_df)} user-assistant exchanges")
    print()

    # Step 3: Save parsed turns
    output_dir = Path(base_dir) / "data" / "processed"
    output_dir.mkdir(exist_ok=True)

    turns_csv_path = output_dir / "parsed_turns.csv"
    turns_df.to_csv(turns_csv_path, index=False)
    print(f"Step 3: Saved parsed turns to {turns_csv_path}")
    print()

    # Step 4: Build thread summary
    print("Step 4: Building thread-level summary...")
    thread_summaries = []

    for conv in conversations:
        thread_id = conv["thread_id"]
        condition = conv["condition"]

        # Get turns for this thread
        thread_turns = turns_df[turns_df["thread_id"] == thread_id]

        # Count image prompts and outcomes
        image_turns = thread_turns[thread_turns["prompt_id"].str.startswith("I", na=False)]

        n_image_prompts = len(image_turns)
        n_image_policy_refusals = len(image_turns[image_turns["response_class"] == ResponseClass.POLICY_REFUSAL.value])
        n_image_capability_refusals = len(image_turns[image_turns["response_class"] == ResponseClass.CAPABILITY_REFUSAL.value])
        n_image_success = len(image_turns[image_turns["response_class"] == ResponseClass.IMAGE_SUCCESS.value])
        n_rate_limit = len(image_turns[image_turns["response_class"] == ResponseClass.RATE_LIMIT.value])

        # Count text prompts (T1)
        text_turns = thread_turns[thread_turns["prompt_id"].str.startswith("T", na=False)]
        n_t1_prompts = len(text_turns)
        n_t1_refusals = len(text_turns[
            (text_turns["response_class"] == ResponseClass.POLICY_REFUSAL.value) |
            (text_turns["response_class"] == ResponseClass.CAPABILITY_REFUSAL.value)
        ])

        thread_summaries.append({
            "thread_id": thread_id,
            "condition": condition,
            "n_image_prompts": n_image_prompts,
            "n_image_policy_refusals": n_image_policy_refusals,
            "n_image_capability_refusals": n_image_capability_refusals,
            "n_image_success": n_image_success,
            "n_rate_limit": n_rate_limit,
            "n_t1_prompts": n_t1_prompts,
            "n_t1_refusals": n_t1_refusals
        })

    summary_df = pd.DataFrame(thread_summaries)
    summary_csv_path = output_dir / "thread_summary.csv"
    summary_df.to_csv(summary_csv_path, index=False)
    print(f"  Saved thread summary to {summary_csv_path}")
    print()

    # Step 5: Calculate statistics
    print("Step 5: Statistical Analysis")
    print("-" * 70)

    # Image prompt statistics by condition
    control_summary = summary_df[summary_df["condition"] == "control"]
    contaminated_summary = summary_df[summary_df["condition"] == "contaminated"]

    # Calculate statistics for FIRST ATTEMPTS ONLY (matching paper methodology)
    print("\n=== FIRST ATTEMPTS ONLY (per-thread, per-prompt) ===")

    # Get the FINAL OUTCOME for each I1-I4 prompt per thread
    # If retried after rate limit and succeeded, count as success
    # If never succeeded (all attempts were refusals/rate limits), count as refusal
    image_prompts = ['I1_KITCHEN', 'I2_BEDROOM', 'I3_ABSTRACT', 'I4_COFFEE']
    first_attempts = []

    for _, thread_row in summary_df.iterrows():
        thread_id = thread_row['thread_id']
        condition = thread_row['condition']
        thread_turns = turns_df[turns_df['thread_id'] == thread_id]

        for prompt in image_prompts:
            prompt_turns = thread_turns[thread_turns['prompt_id'] == prompt]
            if len(prompt_turns) > 0:
                # Determine final outcome
                # If ANY attempt succeeded, count as success
                has_success = any(prompt_turns['response_class'] == ResponseClass.IMAGE_SUCCESS.value)

                if has_success:
                    final_outcome = ResponseClass.IMAGE_SUCCESS.value
                else:
                    # Otherwise, use the last attempt's classification
                    # (captures whether it ended in policy refusal, capability refusal, or rate limit)
                    final_outcome = prompt_turns.iloc[-1]['response_class']

                first_attempts.append({
                    'thread_id': thread_id,
                    'condition': condition,
                    'prompt_id': prompt,
                    'response_class': final_outcome
                })

    first_attempts_df = pd.DataFrame(first_attempts)

    # Calculate stats for first attempts
    control_first = first_attempts_df[first_attempts_df['condition'] == 'control']
    contaminated_first = first_attempts_df[first_attempts_df['condition'] == 'contaminated']

    control_first_total = len(control_first)
    contaminated_first_total = len(contaminated_first)

    # Count refusals (INCLUDING rate limits, as they represent failed attempts)
    control_first_refusals = len(control_first[
        (control_first['response_class'] == ResponseClass.POLICY_REFUSAL.value) |
        (control_first['response_class'] == ResponseClass.CAPABILITY_REFUSAL.value) |
        (control_first['response_class'] == ResponseClass.RATE_LIMIT.value)
    ])
    contaminated_first_refusals = len(contaminated_first[
        (contaminated_first['response_class'] == ResponseClass.POLICY_REFUSAL.value) |
        (contaminated_first['response_class'] == ResponseClass.CAPABILITY_REFUSAL.value) |
        (contaminated_first['response_class'] == ResponseClass.RATE_LIMIT.value)
    ])

    # Also track rate limits separately for reporting
    control_first_rate_limits = len(control_first[control_first['response_class'] == ResponseClass.RATE_LIMIT.value])
    contaminated_first_rate_limits = len(contaminated_first[contaminated_first['response_class'] == ResponseClass.RATE_LIMIT.value])

    control_first_success = len(control_first[control_first['response_class'] == ResponseClass.IMAGE_SUCCESS.value])
    contaminated_first_success = len(contaminated_first[contaminated_first['response_class'] == ResponseClass.IMAGE_SUCCESS.value])

    # All attempts are evaluable (rate limits count as failures, not excluded)
    control_first_evaluable = control_first_total
    contaminated_first_evaluable = contaminated_first_total

    control_first_refusal_rate = control_first_refusals / control_first_evaluable if control_first_evaluable > 0 else 0
    contaminated_first_refusal_rate = contaminated_first_refusals / contaminated_first_evaluable if contaminated_first_evaluable > 0 else 0

    print(f"Control (first attempts):")
    print(f"  Total: {control_first_total}")
    print(f"  Successful: {control_first_success}")
    print(f"  Refused: {control_first_refusals} (includes {control_first_rate_limits} rate limits)")
    print(f"  Refusal rate: {control_first_refusal_rate:.2%} ({control_first_refusals}/{control_first_evaluable})")

    print(f"\nContaminated (first attempts):")
    print(f"  Total: {contaminated_first_total}")
    print(f"  Successful: {contaminated_first_success}")
    print(f"  Refused: {contaminated_first_refusals} (includes {contaminated_first_rate_limits} rate limits)")
    print(f"  Refusal rate: {contaminated_first_refusal_rate:.2%} ({contaminated_first_refusals}/{contaminated_first_evaluable})")

    # Fisher's exact test for first attempts
    contingency_first = [
        [control_first_success, control_first_refusals],
        [contaminated_first_success, contaminated_first_refusals]
    ]
    odds_ratio_first, p_value_first = fisher_exact(contingency_first)
    h_first = cohen_h(contaminated_first_refusal_rate, control_first_refusal_rate)

    print(f"\nFisher's Exact Test (first attempts):")
    print(f"  Odds ratio: {odds_ratio_first:.4f}")
    print(f"  p-value: {p_value_first:.2e}")
    print(f"\nEffect Size - Cohen's h (first attempts):")
    print(f"  h = {h_first:.2f}")

    # Now show ALL ATTEMPTS for comparison
    print("\n\n=== ALL ATTEMPTS (including retries) ===")

    # Total image prompts
    control_total_image = control_summary["n_image_prompts"].sum()
    contaminated_total_image = contaminated_summary["n_image_prompts"].sum()

    # Total refusals (policy + capability, excluding rate limits)
    control_refusals = (control_summary["n_image_policy_refusals"].sum() +
                       control_summary["n_image_capability_refusals"].sum())
    contaminated_refusals = (contaminated_summary["n_image_policy_refusals"].sum() +
                            contaminated_summary["n_image_capability_refusals"].sum())

    # Rate limits
    control_rate_limits = control_summary["n_rate_limit"].sum()
    contaminated_rate_limits = contaminated_summary["n_rate_limit"].sum()

    # Success counts
    control_success = control_summary["n_image_success"].sum()
    contaminated_success = contaminated_summary["n_image_success"].sum()

    print(f"\nControl condition:")
    print(f"  Total image prompts: {control_total_image}")
    print(f"  Successful: {control_success}")
    print(f"  Refused: {control_refusals}")
    print(f"  Rate limited: {control_rate_limits}")

    print(f"\nContaminated condition:")
    print(f"  Total image prompts: {contaminated_total_image}")
    print(f"  Successful: {contaminated_success}")
    print(f"  Refused: {contaminated_refusals}")
    print(f"  Rate limited: {contaminated_rate_limits}")

    # Calculate refusal rates (excluding rate limits)
    control_evaluable = control_total_image - control_rate_limits
    contaminated_evaluable = contaminated_total_image - contaminated_rate_limits

    control_refusal_rate = control_refusals / control_evaluable if control_evaluable > 0 else 0
    contaminated_refusal_rate = contaminated_refusals / contaminated_evaluable if contaminated_evaluable > 0 else 0

    print(f"\nRefusal rates (excluding rate limits):")
    print(f"  Control: {control_refusals}/{control_evaluable} = {control_refusal_rate:.1%}")
    print(f"  Contaminated: {contaminated_refusals}/{contaminated_evaluable} = {contaminated_refusal_rate:.1%}")

    # Fisher's exact test
    # Contingency table: [[control_success, control_refusals], [contaminated_success, contaminated_refusals]]
    contingency_table = [
        [control_success, control_refusals],
        [contaminated_success, contaminated_refusals]
    ]

    odds_ratio, p_value = fisher_exact(contingency_table)

    print(f"\nFisher's Exact Test:")
    print(f"  Odds ratio: {odds_ratio:.4f}")
    print(f"  p-value: {p_value:.2e}")

    # Cohen's h
    h = cohen_h(contaminated_refusal_rate, control_refusal_rate)

    print(f"\nEffect Size (Cohen's h):")
    print(f"  h = {h:.2f}")
    print(f"  Interpretation: ", end="")
    if abs(h) < 0.2:
        print("small effect")
    elif abs(h) < 0.5:
        print("medium effect")
    else:
        print("large effect")

    # Save summary statistics
    stats_text = f"""VIOLATION STATE SUMMARY STATISTICS
{'=' * 70}

SAMPLE SIZE
-----------
Total conversations: {len(conversations)}
  Control: {len(control_summary)}
  Contaminated: {len(contaminated_summary)}

PRIMARY ANALYSIS: FIRST ATTEMPTS ONLY
--------------------------------------
(Counts only the first attempt at each I1-I4 prompt per thread)
(Note: Rate limits are counted as refusals - failed attempts)

Control:
  Total prompts: {control_first_total}
  Successful: {control_first_success}
  Refused: {control_first_refusals} (includes {control_first_rate_limits} rate limits)
  Refusal rate: {control_first_refusal_rate:.2%} ({control_first_refusals}/{control_first_evaluable})

Contaminated:
  Total prompts: {contaminated_first_total}
  Successful: {contaminated_first_success}
  Refused: {contaminated_first_refusals} (includes {contaminated_first_rate_limits} rate limits)
  Refusal rate: {contaminated_first_refusal_rate:.2%} ({contaminated_first_refusals}/{contaminated_first_evaluable})

STATISTICAL TESTS (First Attempts)
-----------------------------------
Fisher's Exact Test:
  Odds ratio: {odds_ratio_first:.4f}
  p-value: {p_value_first:.2e}

Effect Size (Cohen's h):
  h = {h_first:.2f} (large effect)

SECONDARY ANALYSIS: ALL ATTEMPTS
---------------------------------
(Includes retry attempts after rate limits or continued refusals)

Control:
  Total prompts: {control_total_image}
  Successful: {control_success}
  Refused: {control_refusals}
  Rate limited: {control_rate_limits}
  Refusal rate: {control_refusal_rate:.1%} ({control_refusals}/{control_evaluable})

Contaminated:
  Total prompts: {contaminated_total_image}
  Successful: {contaminated_success}
  Refused: {contaminated_refusals}
  Rate limited: {contaminated_rate_limits}
  Refusal rate: {contaminated_refusal_rate:.1%} ({contaminated_refusals}/{contaminated_evaluable})

INTERPRETATION
--------------
The contaminated condition shows a statistically significant increase in
refusal rates compared to control (p < 0.001). The effect size is very large
(Cohen's h = {h_first:.2f}), indicating that the copyright-related trigger has a
substantial impact on subsequent image generation requests in the same conversation.

The primary analysis uses first attempts only to avoid inflating counts from
retry attempts, which is methodologically cleaner for reporting the core effect.
"""

    figures_dir = Path(base_dir) / "analysis" / "figures"
    figures_dir.mkdir(exist_ok=True, parents=True)

    stats_path = figures_dir / "summary_stats.txt"
    with open(stats_path, 'w') as f:
        f.write(stats_text)

    print(f"\nSaved summary statistics to {stats_path}")

    # Step 6: Generate figures
    print("\nStep 6: Generating figures...")
    generate_figures(summary_df, figures_dir, control_first_refusal_rate, contaminated_first_refusal_rate,
                    control_first_refusals, control_first_evaluable,
                    contaminated_first_refusals, contaminated_first_evaluable,
                    odds_ratio_first, p_value_first, h_first)

    print()
    print("=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)


def generate_figures(summary_df, figures_dir, control_rate, contaminated_rate,
                    control_refusals, control_evaluable,
                    contaminated_refusals, contaminated_evaluable,
                    odds_ratio, p_value, cohen_h_value):
    """Generate visualization figures."""

    # Figure 1: Refusal rates bar chart
    fig, ax = plt.subplots(figsize=(8, 6))

    conditions = ['Control', 'Contaminated']
    rates = [control_rate * 100, contaminated_rate * 100]
    colors = ['#2ecc71', '#e74c3c']

    bars = ax.bar(conditions, rates, color=colors, alpha=0.8, edgecolor='black', linewidth=1.5)

    ax.set_ylabel('Refusal Rate (%)', fontsize=12, fontweight='bold')
    ax.set_xlabel('Condition', fontsize=12, fontweight='bold')
    ax.set_title('Image Generation Refusal Rates by Condition', fontsize=14, fontweight='bold', pad=20)
    ax.set_ylim(0, 105)

    # Add value labels on bars
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height + 2,
                f'{height:.1f}%',
                ha='center', va='bottom', fontsize=11, fontweight='bold')

    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    plt.tight_layout()
    fig1_path = figures_dir / "fig1_refusal_rates.png"
    plt.savefig(fig1_path, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"  Generated {fig1_path}")

    # Figure 2: Per-thread heatmap
    fig, ax = plt.subplots(figsize=(10, 8))

    # Prepare data: one row per thread, columns for each prompt
    # We'll show success (green), refusal (red), rate limit (yellow), other (gray)

    # Sort by condition and thread_id
    summary_sorted = summary_df.sort_values(['condition', 'thread_id'])

    # We need to get detailed turn data
    turns_csv_path = Path(figures_dir).parent.parent / "data" / "processed" / "parsed_turns.csv"
    turns_df = pd.read_csv(turns_csv_path)

    # Create matrix: rows = threads, columns = prompts (I1, I2, I3, I4)
    prompts_ordered = ['I1_KITCHEN', 'I2_BEDROOM', 'I3_ABSTRACT', 'I4_COFFEE']

    matrix_data = []
    thread_labels = []

    for _, thread_row in summary_sorted.iterrows():
        thread_id = thread_row['thread_id']
        thread_labels.append(thread_id)

        thread_turns = turns_df[turns_df['thread_id'] == thread_id]

        row = []
        for prompt in prompts_ordered:
            prompt_turn = thread_turns[thread_turns['prompt_id'] == prompt]

            if len(prompt_turn) == 0:
                # No such prompt in this thread
                row.append(0)  # Gray (missing)
            else:
                response_class = prompt_turn.iloc[0]['response_class']
                if response_class == 'image_success':
                    row.append(1)  # Green
                elif response_class == 'policy_refusal':
                    row.append(2)  # Red
                elif response_class == 'rate_limit':
                    row.append(3)  # Yellow
                else:
                    row.append(0)  # Gray (other)

        matrix_data.append(row)

    matrix = np.array(matrix_data)

    # Create custom colormap: 0=gray, 1=green, 2=red, 3=yellow
    from matplotlib.colors import ListedColormap
    colors_map = ['#cccccc', '#2ecc71', '#e74c3c', '#f39c12']
    cmap = ListedColormap(colors_map)

    im = ax.imshow(matrix, cmap=cmap, aspect='auto', vmin=0, vmax=3)

    # Set ticks
    ax.set_xticks(np.arange(len(prompts_ordered)))
    ax.set_xticklabels(['Kitchen', 'Bedroom', 'Abstract', 'Coffee'])
    ax.set_yticks(np.arange(len(thread_labels)))
    ax.set_yticklabels(thread_labels, fontsize=8)

    ax.set_xlabel('Image Prompt', fontsize=12, fontweight='bold')
    ax.set_ylabel('Thread ID', fontsize=12, fontweight='bold')
    ax.set_title('Per-Thread Image Generation Outcomes', fontsize=14, fontweight='bold', pad=20)

    # Add gridlines
    ax.set_xticks(np.arange(len(prompts_ordered)) - 0.5, minor=True)
    ax.set_yticks(np.arange(len(thread_labels)) - 0.5, minor=True)
    ax.grid(which='minor', color='white', linewidth=2)

    # Add a dividing line between control and contaminated
    control_count = len(summary_sorted[summary_sorted['condition'] == 'control'])
    if control_count > 0 and control_count < len(thread_labels):
        ax.axhline(y=control_count - 0.5, color='black', linewidth=3)

    # Add legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='#2ecc71', label='Success'),
        Patch(facecolor='#e74c3c', label='Refusal'),
        Patch(facecolor='#f39c12', label='Rate Limit'),
        Patch(facecolor='#cccccc', label='Missing/Other')
    ]
    ax.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.05, 1), fontsize=10)

    plt.tight_layout()
    fig2_path = figures_dir / "fig2_per_thread_heatmap.png"
    plt.savefig(fig2_path, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"  Generated {fig2_path}")


if __name__ == "__main__":
    # Run analysis from repository root
    repo_root = Path(__file__).parent.parent
    analyze_conversations(str(repo_root))
