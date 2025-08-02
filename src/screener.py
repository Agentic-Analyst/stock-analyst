#!/usr/bin/env python3
"""
screener.py - LLM-powered stock screening and analysis of filtered articles.

This module uses AI prompts stored in external markdown files to analyze news articles
for investment insights including growth catalysts, risks, and mitigation strategies.

▶ Usage:
    python src/screener.py --ticker NVDA --output-report
    python src/screener.py --ticker NVDA --min-confidence 0.7 --detailed-analysis
"""

from __future__ import annotations
import os, csv, argparse, pathlib, re, json
from datetime import datetime
from typing import Dict, List, Tuple, Set, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
import yaml

# Conditionally import LLM functionality
try:
    from llms import gpt_4o_mini
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False
    def gpt_4o_mini(*args, **kwargs):
        raise ImportError("LLM functionality not available. Please check llms.py")

DATA_ROOT = pathlib.Path("data")
PROMPTS_ROOT = pathlib.Path("prompts")

def load_prompt(prompt_name: str) -> str:
    """Load a prompt template from the prompts directory."""
    prompt_file = PROMPTS_ROOT / f"{prompt_name}.md"
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
    return prompt_file.read_text(encoding="utf-8")

@dataclass
class Catalyst:
    """Represents a growth catalyst identified in articles."""
    type: str  # 'product', 'market', 'partnership', 'technology', 'financial'
    description: str
    confidence: float  # 0.0 to 1.0
    supporting_evidence: List[str]
    articles_mentioned: List[str]
    timeline: str  # 'immediate', 'short-term', 'medium-term', 'long-term'
    llm_reasoning: Optional[str] = None  # AI reasoning for this catalyst
    llm_confidence: Optional[float] = None  # LLM-provided confidence score

@dataclass
class Risk:
    """Represents a risk identified in articles."""
    type: str  # 'market', 'competitive', 'regulatory', 'technological', 'financial'
    description: str
    severity: str  # 'low', 'medium', 'high', 'critical'
    confidence: float  # 0.0 to 1.0
    supporting_evidence: List[str]
    articles_mentioned: List[str]
    potential_impact: str
    llm_reasoning: Optional[str] = None  # AI reasoning for this risk
    llm_confidence: Optional[float] = None  # LLM-provided confidence score

@dataclass
class Mitigation:
    """Represents risk mitigation strategies."""
    risk_addressed: str
    strategy: str
    confidence: float
    supporting_evidence: List[str]
    articles_mentioned: List[str]
    effectiveness: str  # 'low', 'medium', 'high'
    company_action: Optional[str] = None  # What the company is doing/planning
    llm_reasoning: Optional[str] = None  # AI reasoning for this mitigation
    llm_confidence: Optional[float] = None  # LLM-provided confidence score

class ArticleScreener:
    def __init__(self, ticker: str):
        self.ticker = ticker.upper()
        self.company_dir = DATA_ROOT / self.ticker
        self.filtered_dir = self.company_dir / "filtered"
        
        # Cost tracking for LLM usage
        self.total_llm_cost = 0.0
        self.llm_call_count = 0

    # ============= LLM-POWERED ANALYSIS METHODS =============
    
    def _create_catalyst_analysis_prompt(self, article_content: str, company_ticker: str) -> List[Dict]:
        """Create Chain-of-Thought prompt for catalyst analysis."""
        system_prompt = load_prompt("catalyst_analysis")
        user_prompt = load_prompt("catalyst_user").format(
            company_ticker=company_ticker,
            article_content=article_content
        )
        
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

    def _create_risk_analysis_prompt(self, article_content: str, company_ticker: str) -> List[Dict]:
        """Create Chain-of-Thought prompt for risk analysis."""
        system_prompt = load_prompt("risk_analysis")
        user_prompt = load_prompt("risk_user").format(
            company_ticker=company_ticker,
            article_content=article_content
        )
        
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

    def _create_mitigation_analysis_prompt(self, article_content: str, company_ticker: str, identified_risks: List[Risk]) -> List[Dict]:
        """Create prompt for analyzing risk mitigation strategies."""
        risk_summary = "\n".join([f"- {risk.type}: {risk.description}" for risk in identified_risks])
        
        system_prompt = load_prompt("mitigation_analysis")
        user_prompt = load_prompt("mitigation_user").format(
            company_ticker=company_ticker,
            article_content=article_content,
            risk_summary=risk_summary
        )
        
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

    def _parse_llm_json_response(self, response_text: str, response_type: str) -> Dict:
        """Safely parse LLM JSON response with error handling."""
        try:
            # Clean the response text
            response_text = response_text.strip()
            
            # Extract JSON if wrapped in markdown code blocks
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()
            elif "```" in response_text:
                start = response_text.find("```") + 3
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()
            
            # Parse JSON
            parsed = json.loads(response_text)
            return parsed
            
        except json.JSONDecodeError as e:
            print(f"[warn] Failed to parse LLM {response_type} response as JSON: {e}")
            print(f"[warn] Raw response: {response_text[:200]}...")
            return {response_type: []}
        except Exception as e:
            print(f"[warn] Error processing LLM {response_type} response: {e}")
            return {response_type: []}

    def analyze_article_with_llm(self, article: Dict) -> Tuple[List[Catalyst], List[Risk], List[Mitigation]]:
        """Analyze a single article using LLM for comprehensive insights."""
        if not LLM_AVAILABLE:
            return [], [], []
            
        article_content = f"Title: {article['title']}\n\nContent: {article['text']}"
        catalysts = []
        risks = []
        mitigations = []
        
        try:
            # Step 1: Analyze Growth Catalysts
            print(f"[llm] Analyzing catalysts for article: {article['file_name'][:50]}...")
            catalyst_prompt = self._create_catalyst_analysis_prompt(article_content, self.ticker)
            catalyst_response, cost1 = gpt_4o_mini(catalyst_prompt)
            self.total_llm_cost += cost1
            self.llm_call_count += 1
            catalyst_data = self._parse_llm_json_response(catalyst_response, "catalysts")
            
            for cat_data in catalyst_data.get("catalysts", []):
                catalyst = Catalyst(
                    type=cat_data.get("type", "unknown").lower(),
                    description=cat_data.get("description", ""),
                    confidence=cat_data.get("confidence", 0.5),
                    supporting_evidence=cat_data.get("supporting_evidence", []),
                    articles_mentioned=[article['file_name']],
                    timeline=cat_data.get("timeline", "medium-term").lower().replace("_", "-"),
                    llm_reasoning=cat_data.get("reasoning", ""),
                    llm_confidence=cat_data.get("confidence", 0.5)
                )
                catalysts.append(catalyst)
            
            # Step 2: Analyze Risks  
            print(f"[llm] Analyzing risks for article: {article['file_name'][:50]}...")
            risk_prompt = self._create_risk_analysis_prompt(article_content, self.ticker)
            risk_response, cost2 = gpt_4o_mini(risk_prompt)
            self.total_llm_cost += cost2
            self.llm_call_count += 1
            risk_data = self._parse_llm_json_response(risk_response, "risks")
            
            for risk_data_item in risk_data.get("risks", []):
                risk = Risk(
                    type=risk_data_item.get("type", "unknown").lower(),
                    description=risk_data_item.get("description", ""),
                    severity=risk_data_item.get("severity", "medium").lower(),
                    confidence=risk_data_item.get("confidence", 0.5),
                    supporting_evidence=risk_data_item.get("supporting_evidence", []),
                    articles_mentioned=[article['file_name']],
                    potential_impact=risk_data_item.get("potential_impact", ""),
                    llm_reasoning=risk_data_item.get("reasoning", ""),
                    llm_confidence=risk_data_item.get("confidence", 0.5)
                )
                risks.append(risk)
            
            # Step 3: Analyze Mitigations
            if risks:  # Only analyze mitigations if risks were found
                print(f"[llm] Analyzing mitigations for article: {article['file_name'][:50]}...")
                mitigation_prompt = self._create_mitigation_analysis_prompt(article_content, self.ticker, risks)
                mitigation_response, cost3 = gpt_4o_mini(mitigation_prompt)
                self.total_llm_cost += cost3
                self.llm_call_count += 1
                mitigation_data = self._parse_llm_json_response(mitigation_response, "mitigations")
                
                for mit_data in mitigation_data.get("mitigations", []):
                    mitigation = Mitigation(
                        risk_addressed=mit_data.get("risk_addressed", ""),
                        strategy=mit_data.get("strategy", ""),
                        confidence=mit_data.get("confidence", 0.5),
                        supporting_evidence=mit_data.get("supporting_evidence", []),
                        articles_mentioned=[article['file_name']],
                        effectiveness=mit_data.get("effectiveness", "medium").lower(),
                        company_action=mit_data.get("company_action", ""),
                        llm_reasoning=mit_data.get("reasoning", ""),
                        llm_confidence=mit_data.get("confidence", 0.5)
                    )
                    mitigations.append(mitigation)
            
        except Exception as e:
            print(f"[error] LLM analysis failed for article {article['file_name']}: {e}")
            
        return catalysts, risks, mitigations

    # ============= END LLM METHODS =============

    def load_filtered_articles(self) -> List[Dict]:
        """Load all filtered articles."""
        if not self.filtered_dir.exists():
            print(f"[error] Filtered directory {self.filtered_dir} does not exist")
            return []
        
        articles = []
        for md_file in self.filtered_dir.glob("filtered_*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                
                # Parse frontmatter
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        frontmatter = yaml.safe_load(parts[1]) or {}
                        text_content = parts[2].strip()
                    else:
                        frontmatter = {}
                        text_content = content
                else:
                    frontmatter = {}
                    text_content = content
                
                articles.append({
                    "file_path": md_file,
                    "file_name": md_file.name,
                    "title": frontmatter.get("title", ""),
                    "source_url": frontmatter.get("source_url", ""),
                    "publish_date": frontmatter.get("publish_date", ""),
                    "text": text_content,
                    "word_count": len(text_content.split()),
                })
            except Exception as e:
                print(f"[warn] Could not load {md_file}: {e}")
        
        return articles

    def extract_catalysts(self, articles: List[Dict]) -> List[Catalyst]:
        """Extract growth catalysts from articles using LLM analysis."""
        if not LLM_AVAILABLE:
            print("[error] LLM functionality required for analysis but not available")
            return []
            
        catalysts = []
        print(f"[info] Using LLM analysis for {len(articles)} articles...")
        
        for article in articles:
            llm_catalysts, _, _ = self.analyze_article_with_llm(article)
            catalysts.extend(llm_catalysts)
        
        return self._merge_similar_catalysts(catalysts)

    def extract_risks(self, articles: List[Dict]) -> List[Risk]:
        """Extract risks from articles using LLM analysis."""
        if not LLM_AVAILABLE:
            print("[error] LLM functionality required for analysis but not available")
            return []
            
        risks = []
        
        for article in articles:
            _, llm_risks, _ = self.analyze_article_with_llm(article)
            risks.extend(llm_risks)
        
        return self._merge_similar_risks(risks)

    def extract_mitigations(self, articles: List[Dict], identified_risks: List[Risk]) -> List[Mitigation]:
        """Extract risk mitigation strategies using LLM analysis."""
        if not LLM_AVAILABLE:
            print("[error] LLM functionality required for analysis but not available")
            return []
            
        mitigations = []
        
        for article in articles:
            _, _, llm_mitigations = self.analyze_article_with_llm(article)
            mitigations.extend(llm_mitigations)
        
        return self._merge_similar_mitigations(mitigations)

    def _merge_similar_catalysts(self, catalysts: List[Catalyst]) -> List[Catalyst]:
        """Merge similar catalysts to avoid duplicates."""
        if not catalysts:
            return []
        
        merged = []
        used_indices = set()
        
        for i, catalyst in enumerate(catalysts):
            if i in used_indices:
                continue
                
            similar_catalysts = [catalyst]
            used_indices.add(i)
            
            # Find similar catalysts
            for j, other_catalyst in enumerate(catalysts[i+1:], i+1):
                if j in used_indices:
                    continue
                    
                if (catalyst.type == other_catalyst.type and 
                    self._are_descriptions_similar(catalyst.description, other_catalyst.description)):
                    similar_catalysts.append(other_catalyst)
                    used_indices.add(j)
            
            # Merge if multiple similar catalysts found
            if len(similar_catalysts) > 1:
                merged_catalyst = self._merge_catalyst_group(similar_catalysts)
                merged.append(merged_catalyst)
            else:
                merged.append(catalyst)
        
        return merged

    def _merge_similar_risks(self, risks: List[Risk]) -> List[Risk]:
        """Merge similar risks to avoid duplicates."""
        # Similar logic to catalyst merging
        if not risks:
            return []
        
        merged = []
        used_indices = set()
        
        for i, risk in enumerate(risks):
            if i in used_indices:
                continue
                
            similar_risks = [risk]
            used_indices.add(i)
            
            for j, other_risk in enumerate(risks[i+1:], i+1):
                if j in used_indices:
                    continue
                    
                if (risk.type == other_risk.type and 
                    self._are_descriptions_similar(risk.description, other_risk.description)):
                    similar_risks.append(other_risk)
                    used_indices.add(j)
            
            if len(similar_risks) > 1:
                merged_risk = self._merge_risk_group(similar_risks)
                merged.append(merged_risk)
            else:
                merged.append(risk)
        
        return merged

    def _merge_similar_mitigations(self, mitigations: List[Mitigation]) -> List[Mitigation]:
        """Merge similar mitigations."""
        # Similar merging logic
        return mitigations  # Simplified for now

    def _are_descriptions_similar(self, desc1: str, desc2: str, threshold: float = 0.6) -> bool:
        """Check if two descriptions are similar."""
        # Simple similarity check based on common words
        words1 = set(re.findall(r'\b\w+\b', desc1.lower()))
        words2 = set(re.findall(r'\b\w+\b', desc2.lower()))
        
        if not words1 or not words2:
            return False
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        similarity = intersection / union if union > 0 else 0
        return similarity >= threshold

    def _merge_catalyst_group(self, catalysts: List[Catalyst]) -> Catalyst:
        """Merge a group of similar catalysts."""
        # Combine evidence and articles
        all_evidence = []
        all_articles = []
        total_confidence = 0
        
        for catalyst in catalysts:
            all_evidence.extend(catalyst.supporting_evidence)
            all_articles.extend(catalyst.articles_mentioned)
            total_confidence += catalyst.confidence
        
        # Create merged catalyst
        base_catalyst = catalysts[0]
        return Catalyst(
            type=base_catalyst.type,
            description=base_catalyst.description,
            confidence=min(1.0, total_confidence / len(catalysts) + 0.1),  # Boost merged confidence
            supporting_evidence=list(set(all_evidence))[:5],  # Unique evidence, max 5
            articles_mentioned=list(set(all_articles)),
            timeline=base_catalyst.timeline
        )

    def _merge_risk_group(self, risks: List[Risk]) -> Risk:
        """Merge a group of similar risks."""
        all_evidence = []
        all_articles = []
        total_confidence = 0
        
        for risk in risks:
            all_evidence.extend(risk.supporting_evidence)
            all_articles.extend(risk.articles_mentioned)
            total_confidence += risk.confidence
        
        base_risk = risks[0]
        return Risk(
            type=base_risk.type,
            description=base_risk.description,
            severity=base_risk.severity,
            confidence=min(1.0, total_confidence / len(risks) + 0.1),
            supporting_evidence=list(set(all_evidence))[:5],
            articles_mentioned=list(set(all_articles)),
            potential_impact=base_risk.potential_impact
        )

    def generate_screening_report(self, catalysts: List[Catalyst], risks: List[Risk], 
                                mitigations: List[Mitigation], output_file: pathlib.Path):
        """Generate comprehensive screening report with LLM insights."""
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"# {self.ticker} LLM-Powered Stock Screening Analysis\n\n")
            f.write(f"**Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"**Analysis Method:** LLM-Enhanced Analysis\n\n")
            
            # Executive Summary
            f.write("## 📊 Executive Summary\n\n")
            f.write(f"**Growth Catalysts Identified:** {len(catalysts)}\n")
            f.write(f"**Risks Identified:** {len(risks)}\n")
            f.write(f"**Mitigation Strategies:** {len(mitigations)}\n\n")
            
            # High-level insights
            if catalysts or risks:
                f.write("### Key Insights\n\n")
                
                # Top catalyst by confidence
                if catalysts:
                    top_catalyst = max(catalysts, key=lambda x: x.confidence)
                    f.write(f"**Strongest Growth Driver:** {top_catalyst.type.title()} - {top_catalyst.description[:100]}...\n")
                
                # Highest risk by severity/confidence
                if risks:
                    top_risk = max(risks, key=lambda x: (x.severity == 'critical', x.severity == 'high', x.confidence))
                    f.write(f"**Primary Risk Factor:** {top_risk.type.title()} - {top_risk.description[:100]}...\n")
                
                f.write("\n")
            
            # Growth Catalysts Section  
            f.write("## 🚀 Growth Catalysts\n\n")
            if catalysts:
                for i, catalyst in enumerate(sorted(catalysts, key=lambda x: x.confidence, reverse=True), 1):
                    f.write(f"### Catalyst {i}: {catalyst.type.title()} Opportunity\n\n")
                    f.write(f"**Confidence:** {catalyst.confidence:.1%}")
                    if catalyst.llm_confidence:
                        f.write(f" (LLM: {catalyst.llm_confidence:.1%})")
                    f.write(f"\n**Timeline:** {catalyst.timeline.title()}\n")
                    f.write(f"**Description:** {catalyst.description}\n\n")
                    
                    if catalyst.llm_reasoning:
                        f.write("**AI Analysis:**\n")
                        f.write(f"> {catalyst.llm_reasoning}\n\n")
                    
                    f.write("**Supporting Evidence:**\n")
                    for evidence in catalyst.supporting_evidence:
                        f.write(f"- {evidence}\n")
                    f.write("\n")
                    
                    f.write(f"**Source Articles:** {', '.join(catalyst.articles_mentioned)}\n\n")
                    f.write("---\n\n")
            else:
                f.write("No specific growth catalysts identified in the analyzed articles.\n\n")
            
            # Risks Section
            f.write("## ⚠️ Risk Analysis\n\n")
            if risks:
                for i, risk in enumerate(sorted(risks, key=lambda x: (x.severity == 'critical', x.severity == 'high', x.confidence), reverse=True), 1):
                    severity_emoji = {'critical': '🚨', 'high': '⚠️', 'medium': '⚡', 'low': '💭'}
                    f.write(f"### Risk {i}: {risk.type.title()} Risk {severity_emoji.get(risk.severity, '⚠️')}\n\n")
                    f.write(f"**Severity:** {risk.severity.title()}\n")
                    f.write(f"**Confidence:** {risk.confidence:.1%}")
                    if risk.llm_confidence:
                        f.write(f" (LLM: {risk.llm_confidence:.1%})")
                    f.write(f"\n**Description:** {risk.description}\n")
                    f.write(f"**Potential Impact:** {risk.potential_impact}\n\n")
                    
                    if risk.llm_reasoning:
                        f.write("**AI Analysis:**\n")
                        f.write(f"> {risk.llm_reasoning}\n\n")
                    
                    f.write("**Supporting Evidence:**\n")
                    for evidence in risk.supporting_evidence:
                        f.write(f"- {evidence}\n")
                    f.write("\n")
                    
                    f.write(f"**Source Articles:** {', '.join(risk.articles_mentioned)}\n\n")
                    f.write("---\n\n")
            else:
                f.write("No specific risks identified in the analyzed articles.\n\n")
            
            # Mitigation Strategies Section
            f.write("## 🛡️ Risk Mitigation & Company Response\n\n")
            if mitigations:
                for i, mitigation in enumerate(sorted(mitigations, key=lambda x: x.confidence, reverse=True), 1):
                    effectiveness_emoji = {'high': '✅', 'medium': '⚡', 'low': '❓'}
                    f.write(f"### Mitigation {i}: {effectiveness_emoji.get(mitigation.effectiveness, '⚡')} Strategy\n\n")
                    f.write(f"**Risk Addressed:** {mitigation.risk_addressed[:100]}...\n")
                    f.write(f"**Strategy:** {mitigation.strategy}\n")
                    f.write(f"**Effectiveness:** {mitigation.effectiveness.title()}\n")
                    f.write(f"**Confidence:** {mitigation.confidence:.1%}")
                    if mitigation.llm_confidence:
                        f.write(f" (LLM: {mitigation.llm_confidence:.1%})")
                    f.write("\n\n")
                    
                    if mitigation.company_action:
                        f.write(f"**Company Action:** {mitigation.company_action}\n\n")
                    
                    if mitigation.llm_reasoning:
                        f.write("**AI Analysis:**\n")
                        f.write(f"> {mitigation.llm_reasoning}\n\n")
                    
                    f.write("**Supporting Evidence:**\n")
                    for evidence in mitigation.supporting_evidence:
                        f.write(f"- {evidence}\n")
                    f.write("\n")
                    
                    f.write(f"**Source Articles:** {', '.join(mitigation.articles_mentioned)}\n\n")
                    f.write("---\n\n")
            else:
                f.write("No specific mitigation strategies identified in the analyzed articles.\n\n")
            
            # Investment Thesis Summary
            f.write("## 📈 Investment Thesis Summary\n\n")
            
            # Catalyst summary
            if catalysts:
                f.write("### Growth Potential\n")
                catalyst_types = {}
                for catalyst in catalysts:
                    if catalyst.type not in catalyst_types:
                        catalyst_types[catalyst.type] = []
                    catalyst_types[catalyst.type].append(catalyst)
                
                for cat_type, cat_list in catalyst_types.items():
                    avg_confidence = sum(c.confidence for c in cat_list) / len(cat_list)
                    f.write(f"- **{cat_type.title()} Catalysts:** {len(cat_list)} identified (avg confidence: {avg_confidence:.1%})\n")
                f.write("\n")
            
            # Risk summary
            if risks:
                f.write("### Risk Profile\n")
                risk_by_severity = {}
                for risk in risks:
                    if risk.severity not in risk_by_severity:
                        risk_by_severity[risk.severity] = []
                    risk_by_severity[risk.severity].append(risk)
                
                for severity in ['critical', 'high', 'medium', 'low']:
                    if severity in risk_by_severity:
                        f.write(f"- **{severity.title()} Risks:** {len(risk_by_severity[severity])}\n")
                f.write("\n")
            
            # Overall assessment
            if catalysts and risks:
                catalyst_score = sum(c.confidence for c in catalysts) / len(catalysts)
                risk_score = sum(r.confidence for r in risks) / len(risks)
                net_score = catalyst_score - (risk_score * 0.5)  # Weight risks lower
                
                f.write("### Overall Assessment\n")
                f.write(f"**Catalyst Strength:** {catalyst_score:.1%}\n")
                f.write(f"**Risk Level:** {risk_score:.1%}\n") 
                f.write(f"**Net Outlook Score:** {net_score:.1%}\n\n")
                
                if net_score > 0.6:
                    f.write("**Investment Outlook:** 🟢 Positive - Strong catalysts outweigh identified risks\n")
                elif net_score > 0.3:
                    f.write("**Investment Outlook:** 🟡 Cautiously Positive - Moderate opportunity with manageable risks\n")
                elif net_score > 0:
                    f.write("**Investment Outlook:** 🟡 Neutral - Balanced risk/reward profile\n")
                else:
                    f.write("**Investment Outlook:** 🔴 Cautious - Risks may outweigh near-term catalysts\n")
            
            # Add cost information from LLM usage
            if self.llm_call_count > 0:
                f.write(f"\n## 💰 LLM Analysis Cost Summary\n\n")
                f.write(f"**Total LLM Calls:** {self.llm_call_count}\n")
                f.write(f"**Total Cost:** ${self.total_llm_cost:.6f} USD\n")
                f.write(f"**Average Cost per Call:** ${self.total_llm_cost/self.llm_call_count:.6f} USD\n\n")
            
            f.write(f"\n---\n*Analysis completed using {len(catalysts + risks + mitigations)} insights from filtered articles.*")
            if self.llm_call_count > 0:
                f.write(f" LLM analysis cost: ${self.total_llm_cost:.6f} USD")
            f.write("\n")

    def save_structured_data(self, catalysts: List[Catalyst], risks: List[Risk], 
                           mitigations: List[Mitigation], output_file: pathlib.Path):
        """Save structured data as JSON for further analysis."""
        data = {
            "timestamp": datetime.now().isoformat(),
            "ticker": self.ticker,
            "catalysts": [asdict(c) for c in catalysts],
            "risks": [asdict(r) for r in risks],
            "mitigations": [asdict(m) for m in mitigations]
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

def main():
    parser = argparse.ArgumentParser(description="LLM-Powered Stock Screening: Analyze filtered articles for investment insights")
    parser.add_argument("--ticker", required=True, help="Stock ticker, e.g. NVDA")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="Minimum confidence threshold (0.0-1.0)")
    parser.add_argument("--output-report", action="store_true", help="Generate detailed screening report")
    parser.add_argument("--save-data", action="store_true", help="Save structured data as JSON")
    parser.add_argument("--detailed-analysis", action="store_true", help="Include detailed analysis in output")
    
    args = parser.parse_args()
    
    # Initialize screener
    screener = ArticleScreener(args.ticker)
    
    # Load filtered articles
    print(f"[info] Loading filtered articles for {args.ticker}")
    articles = screener.load_filtered_articles()
    
    if not articles:
        print("[warn] No filtered articles found")
        return
    
    print(f"[info] Analyzing {len(articles)} filtered articles using LLM-Enhanced analysis")
    
    if not LLM_AVAILABLE:
        print("[error] LLM functionality not available. Please check that llms.py is properly configured.")
        return
    print("[info] 🤖 LLM analysis enabled - this will provide deeper insights but take longer and cost API credits")
    
    # Extract insights
    print("[info] Extracting growth catalysts...")
    catalysts = screener.extract_catalysts(articles)
    catalysts = [c for c in catalysts if c.confidence >= args.min_confidence]
    
    print("[info] Identifying risks...")
    risks = screener.extract_risks(articles)
    risks = [r for r in risks if r.confidence >= args.min_confidence]
    
    print("[info] Analyzing mitigation strategies...")
    mitigations = screener.extract_mitigations(articles, risks)
    mitigations = [m for m in mitigations if m.confidence >= args.min_confidence]
    
    # Display summary
    print(f"\n[results] Analysis complete:")
    print(f"  Growth Catalysts: {len(catalysts)}")
    print(f"  Risks Identified: {len(risks)}")
    print(f"  Mitigation Strategies: {len(mitigations)}")
    
    # Display LLM cost information
    if screener.llm_call_count > 0:
        print(f"  LLM Calls Made: {screener.llm_call_count}")
        print(f"  Total LLM Cost: ${screener.total_llm_cost:.6f} USD")
        print(f"  Average Cost per Call: ${screener.total_llm_cost/screener.llm_call_count:.6f} USD")
    
    if args.detailed_analysis:
        print(f"\n[details] Top Catalysts:")
        for i, catalyst in enumerate(sorted(catalysts, key=lambda x: x.confidence, reverse=True)[:3], 1):
            llm_note = f" (LLM: {catalyst.llm_confidence:.1%})" if catalyst.llm_confidence else ""
            print(f"  {i}. [{catalyst.confidence:.1%}{llm_note}] {catalyst.type.title()}: {catalyst.description[:80]}...")
        
        print(f"\n[details] Top Risks:")
        for i, risk in enumerate(sorted(risks, key=lambda x: x.confidence, reverse=True)[:3], 1):
            llm_note = f" (LLM: {risk.llm_confidence:.1%})" if risk.llm_confidence else ""
            print(f"  {i}. [{risk.confidence:.1%}{llm_note}] {risk.type.title()}: {risk.description[:80]}...")
    
    # Generate reports
    if args.output_report:
        report_file = DATA_ROOT / args.ticker / "screening_report.md"
        screener.generate_screening_report(catalysts, risks, mitigations, report_file)
        print(f"[saved] Screening report: {report_file}")
    
    if args.save_data:
        data_file = DATA_ROOT / args.ticker / "screening_data.json"
        screener.save_structured_data(catalysts, risks, mitigations, data_file)
        print(f"[saved] Structured data: {data_file}")
    
    # Quick investment outlook
    if catalysts or risks:
        print(f"\n[insight] Quick Investment Outlook for {args.ticker}:")
        if catalysts:
            avg_catalyst_confidence = sum(c.confidence for c in catalysts) / len(catalysts)
            print(f"  📈 Growth Potential: {avg_catalyst_confidence:.1%} (based on {len(catalysts)} catalysts)")
        
        if risks:
            avg_risk_confidence = sum(r.confidence for r in risks) / len(risks)
            high_severity_risks = len([r for r in risks if r.severity in ['high', 'critical']])
            print(f"  ⚠️  Risk Level: {avg_risk_confidence:.1%} (including {high_severity_risks} high-severity risks)")
        
        if mitigations:
            print(f"  🛡️  Risk Management: {len(mitigations)} mitigation strategies identified")
        
        # Simple net assessment
        if catalysts and risks:
            catalyst_score = sum(c.confidence for c in catalysts) / len(catalysts)
            risk_score = sum(r.confidence for r in risks) / len(risks)
            net_score = catalyst_score - (risk_score * 0.5)
            
            if net_score > 0.4:
                outlook = "🟢 POSITIVE"
            elif net_score > 0.1:
                outlook = "🟡 CAUTIOUS POSITIVE" 
            elif net_score > -0.1:
                outlook = "🟡 NEUTRAL"
            else:
                outlook = "🔴 CAUTIOUS"
            
            print(f"  📊 Net Outlook: {outlook} (Score: {net_score:.2f})")

if __name__ == "__main__":
    main()
