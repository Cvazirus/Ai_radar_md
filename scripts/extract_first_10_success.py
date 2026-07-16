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
    results = []
    
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
            
            # Extract Title
            title = "Unknown"
            for line in user_content.split('\n'):
                if line.startswith("Title:"):
                    title = line.replace("Title:", "").strip()
                    break
            
            # Extract Raw Content
            raw_content = ""
            content_started = False
            for line in user_content.split('\n'):
                if line.startswith("Raw Content:"):
                    raw_content = line.replace("Raw Content:", "").strip()
                    content_started = True
                elif content_started:
                    raw_content += "\n" + line

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
                
                results.append({
                    "number": success_count,
                    "file": filename,
                    "title": title,
                    "category": category,
                    "novelty": novelty,
                    "practicality": practicality,
                    "credibility": credibility,
                    "relevance": relevance,
                    "total_score": total_score,
                    "claims": parsed_json.get("source_claims", []),
                    "uncertainties": parsed_json.get("uncertainties", []),
                    "raw_content": raw_content.strip()
                })
            except Exception:
                continue

    output_path = "/root/ai-radar/scripts/success_runs_details.txt"
    with open(output_path, "w", encoding="utf-8") as out:
        for r in results[:12]: # Write 12 just in case
            out.write(f"=== SUCCESS RUN #{r['number']} ===\n")
            out.write(f"File: {r['file']}\n")
            out.write(f"Title: {r['title']}\n")
            out.write(f"Category: {r['category']}\n")
            out.write(f"Scores: Novelty={r['novelty']}, Practicality={r['practicality']}, Credibility={r['credibility']}, Relevance={r['relevance']} -> Total={r['total_score']:.2f}\n")
            out.write("Claims:\n")
            for claim in r['claims']:
                out.write(f"  - Claim: {claim.get('claim')}\n")
                out.write(f"    Evidence: {claim.get('evidence_text')}\n")
            out.write("Uncertainties:\n")
            for unc in r['uncertainties']:
                out.write(f"  - Field: {unc.get('field')} | Reason: {unc.get('reason')} | Severity: {unc.get('severity')}\n")
            out.write(f"Raw Content: {r['raw_content'][:200]}...\n")
            out.write("-" * 50 + "\n\n")
    print(f"Wrote {min(len(results), 12)} success runs to {output_path}")

if __name__ == "__main__":
    parse_logs()
