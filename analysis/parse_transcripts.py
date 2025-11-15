"""
Transcript parsing module for Violation State study.

This module parses ChatGPT Web conversation transcripts from .txt files
into structured conversation data.
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Optional


def parse_single_transcript(file_path: str) -> Dict:
    """
    Parse a single ChatGPT transcript file into structured conversation data.

    Args:
        file_path: Path to the transcript .txt file

    Returns:
        Dictionary containing:
            - thread_id: Filename without extension (e.g., "control_01")
            - condition: "control" or "contaminated"
            - turns: List of turn dictionaries with speaker, text, turn_index
    """
    file_path = Path(file_path)
    thread_id = file_path.stem  # e.g., "control_01" or "contaminated_01"

    # Determine condition from filename
    if thread_id.startswith("control"):
        condition = "control"
    elif thread_id.startswith("contaminated"):
        condition = "contaminated"
    else:
        condition = "unknown"

    # Read file content
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Parse turns
    turns = []

    # Split on "You said:" and "ChatGPT said:" markers
    # Use regex to find all occurrences and their positions
    user_pattern = r'^(?:You said:|You:)\s*$'
    assistant_pattern = r'^(?:ChatGPT said:|ChatGPT:)\s*$'

    lines = content.split('\n')

    current_speaker = None
    current_text = []
    turn_index = 0

    # Check if file starts with content before any marker (first user turn)
    first_marker_line = None
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if re.match(user_pattern, line_stripped) or re.match(assistant_pattern, line_stripped):
            first_marker_line = i
            break

    # If there's content before the first marker, treat it as the first user turn
    if first_marker_line is not None and first_marker_line > 0:
        initial_content = '\n'.join(lines[:first_marker_line]).strip()
        if initial_content and initial_content != "Share":
            current_speaker = "user"
            current_text = lines[:first_marker_line]

    for i, line in enumerate(lines):
        # Skip lines we already processed as initial content
        if first_marker_line is not None and i < first_marker_line:
            continue

        line_stripped = line.strip()

        # Check if this is a speaker marker
        if re.match(user_pattern, line_stripped):
            # Save previous turn if exists
            if current_speaker is not None and current_text:
                text_content = '\n'.join(current_text).strip()
                if text_content:  # Only add non-empty turns
                    turns.append({
                        "speaker": current_speaker,
                        "text": text_content,
                        "turn_index": turn_index
                    })
                    turn_index += 1

            # Start new user turn
            current_speaker = "user"
            current_text = []

        elif re.match(assistant_pattern, line_stripped):
            # Save previous turn if exists
            if current_speaker is not None and current_text:
                text_content = '\n'.join(current_text).strip()
                if text_content:  # Only add non-empty turns
                    turns.append({
                        "speaker": current_speaker,
                        "text": text_content,
                        "turn_index": turn_index
                    })
                    turn_index += 1

            # Start new assistant turn
            current_speaker = "assistant"
            current_text = []

        else:
            # Add to current turn (skip common noise like "Share")
            if current_speaker is not None and line_stripped and line_stripped != "Share":
                current_text.append(line)

    # Don't forget the last turn
    if current_speaker is not None and current_text:
        text_content = '\n'.join(current_text).strip()
        if text_content:
            turns.append({
                "speaker": current_speaker,
                "text": text_content,
                "turn_index": turn_index
            })

    return {
        "thread_id": thread_id,
        "condition": condition,
        "turns": turns
    }


def load_all_conversations(base_dir: str) -> List[Dict]:
    """
    Load all conversation transcripts from the data directory.

    Args:
        base_dir: Base directory containing transcripts/control/ and transcripts/contaminated/

    Returns:
        List of conversation dictionaries from parse_single_transcript()
    """
    base_path = Path(base_dir)
    conversations = []

    # Load control transcripts
    control_dir = base_path / "transcripts" / "control"
    if control_dir.exists():
        for txt_file in sorted(control_dir.glob("*.txt")):
            conv = parse_single_transcript(str(txt_file))
            conversations.append(conv)

    # Load contaminated transcripts
    contaminated_dir = base_path / "transcripts" / "contaminated"
    if contaminated_dir.exists():
        for txt_file in sorted(contaminated_dir.glob("*.txt")):
            conv = parse_single_transcript(str(txt_file))
            conversations.append(conv)

    return conversations


def get_user_assistant_pairs(conversation: Dict) -> List[tuple]:
    """
    Extract (user_turn, assistant_turn) pairs from a conversation.

    Args:
        conversation: Conversation dictionary from parse_single_transcript()

    Returns:
        List of (user_turn_dict, assistant_turn_dict) tuples
    """
    turns = conversation["turns"]
    pairs = []

    for i in range(len(turns) - 1):
        if turns[i]["speaker"] == "user" and turns[i + 1]["speaker"] == "assistant":
            pairs.append((turns[i], turns[i + 1]))

    return pairs


if __name__ == "__main__":
    # Test the parser
    import sys

    if len(sys.argv) > 1:
        test_file = sys.argv[1]
        result = parse_single_transcript(test_file)
        print(f"Thread ID: {result['thread_id']}")
        print(f"Condition: {result['condition']}")
        print(f"Number of turns: {len(result['turns'])}")
        print("\nTurns:")
        for turn in result['turns']:
            print(f"  [{turn['turn_index']}] {turn['speaker']}: {turn['text'][:50]}...")
    else:
        # Load all from default location
        base_dir = Path(__file__).parent.parent / "data"
        conversations = load_all_conversations(str(base_dir))
        print(f"Loaded {len(conversations)} conversations")

        control_count = sum(1 for c in conversations if c['condition'] == 'control')
        contaminated_count = sum(1 for c in conversations if c['condition'] == 'contaminated')

        print(f"  Control: {control_count}")
        print(f"  Contaminated: {contaminated_count}")
