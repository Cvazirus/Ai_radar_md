import os
import json
import re

def parse_logs():
    log_dir = "/root/.omniroute/call_logs/2026-07-16"
    if not os.path.exists(log_dir):
        print(f"Directory {log_dir} does not exist.")
        return

    files = sorted(os.listdir(log_dir))
    
    success_count = 0
    for filename in files:
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(log_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except Exception:
                continue

            request = data.get("request", {})
            messages = request.get("messages", [])
            user_content = ""
            for msg in messages:
                if msg.get("role") == "user":
                    user_content = msg.get("content", "")
                    break
            
            # Extract Title and Raw Content from prompt
            title_match = re.search(r"Title:\s*(.*?)(?:\r?\n|$)", user_content)
            title = title_match.group(1).strip() if title_match else "Unknown"

            content_match = re.search(r"Raw Content:\s*([\s\S]*)$", user_content)
            raw_content = content_match.group(1).strip() if content_match else ""

            response_body = data.get("responseBody") or {}
            choices = response_body.get("choices", [])
            assistant_content = ""
            if choices:
                assistant_content = choices[0].get("message", {}).get("content", "")

            if not assistant_content:
                continue

            json_text = assistant_content
            code_fence_match = re.search(r"```json\s*([\s\S]*?)\s*```", assistant_content)
            if code_fence_match:
                json_text = code_fence_match.group(1)
            else:
                braces_match = re.search(r"(\{[\s\S]*\})", assistant_content)
                if braces_match:
                    json_text = braces_match.group(1)

            try:
                parsed_json = json.loads(json_text.strip())
                success_count += 1
                category = parsed_json.get("category", "")
                novelty = parsed_json.get("novelty_score", 0)
                practicality = parsed_json.get("practicality_score", 0)
                credibility = parsed_json.get("credibility_score", 0)
                relevance = parsed_json.get("relevance_score", 0)
                total_score = relevance*0.35 + practicality*0.30 + novelty*0.20 + credibility*0.15
                
                print(f"=== SUCCESS RUN #{success_count} ===")
                print(f"File: {filename}")
                print(f"Title: {title}")
                print(f"Category: {category}")
                print(f"Scores: Novelty={novelty}, Practicality={practicality}, Credibility={credibility}, Relevance={relevance} -> Total={total_score:.2f}")
                print("Claims:")
                for claim in parsed_json.get("source_claims", []):
                    print(f"  - Claim: {claim.get('claim')}")
                    print(f"    Evidence: {claim.get('evidence_text')}")
                print("Uncertainties:")
                for unc in parsed_json.get("uncertainties", []):
                    print(f"  - Field: {unc.get('field')} | Reason: {unc.get('reason')} | Severity: {unc.get('severity')}")
                print(f"Raw Content Snippet: {raw_content[:200]}...")
                print("-" * 50 + "\n")
            except Exception:
                continue

if __name__ == "__main__":
    parse_logs()
