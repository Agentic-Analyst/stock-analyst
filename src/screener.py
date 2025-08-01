#!/usr/bin/env python3
"""
screener.py - Systematically screen and analyze filtered articles for investment insights.

▶ Usage:
    python screener.py --ticker NVDA --output-report
    python screener.py --ticker NVDA --min-confidence 0.7 --detailed-analysis
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
        
        # Define catalyst patterns and keywords
        self.catalyst_patterns = {
            'product': {
                'keywords': [
                    'new product', 'product launch', 'next generation', 'innovation',
                    'breakthrough', 'revolutionary', 'cutting-edge', 'advanced',
                    'upgrade', 'enhanced', 'improved performance'
                ],
                'phrases': [
                    r'launch(?:ing|ed)?\s+(?:new|next|latest)',
                    r'introduc(?:ing|ed)\s+(?:new|revolutionary)',
                    r'unveil(?:ing|ed)\s+(?:new|next-gen)',
                    r'(?:new|next)\s+generation\s+of',
                    r'breakthrough\s+in\s+(?:technology|product)',
                ]
            },
            'market': {
                'keywords': [
                    'market expansion', 'new market', 'growing demand', 'market opportunity',
                    'addressable market', 'tam', 'market size', 'market growth',
                    'emerging market', 'untapped market'
                ],
                'phrases': [
                    r'market\s+(?:expand|expansion|growth|opportunity)',
                    r'growing\s+(?:demand|market)',
                    r'addressable\s+market',
                    r'billion.*market',
                    r'market\s+size.*billion',
                ]
            },
            'partnership': {
                'keywords': [
                    'partnership', 'collaboration', 'alliance', 'joint venture',
                    'strategic partnership', 'deal', 'agreement', 'contract',
                    'customer wins', 'major client'
                ],
                'phrases': [
                    r'partner(?:ship)?\s+with',
                    r'collaborat(?:ion|ing)\s+with',
                    r'strategic\s+(?:partnership|alliance)',
                    r'signed.*(?:deal|contract|agreement)',
                    r'major\s+(?:client|customer|deal)',
                ]
            },
            'technology': {
                'keywords': [
                    'technological advancement', 'breakthrough technology', 'r&d',
                    'research and development', 'patent', 'intellectual property',
                    'competitive advantage', 'moat', 'differentiation'
                ],
                'phrases': [
                    r'technological\s+(?:breakthrough|advancement)',
                    r'(?:ai|artificial intelligence)\s+(?:breakthrough|advancement)',
                    r'patent(?:ed|s)?\s+technology',
                    r'competitive\s+(?:advantage|moat)',
                    r'proprietary\s+technology',
                ]
            },
            'financial': {
                'keywords': [
                    'revenue growth', 'profit margin', 'cash flow', 'profitability',
                    'cost reduction', 'efficiency', 'margin expansion',
                    'return on investment', 'roi'
                ],
                'phrases': [
                    r'revenue\s+(?:growth|increase|up)',
                    r'profit\s+margin.*(?:expand|increase|improve)',
                    r'cash\s+flow.*(?:positive|strong|improve)',
                    r'cost\s+(?:reduction|savings|efficiency)',
                    r'margin\s+expansion',
                ]
            }
        }
        
        # Define risk patterns
        self.risk_patterns = {
            'market': {
                'keywords': [
                    'market downturn', 'recession', 'economic slowdown', 'demand decline',
                    'market saturation', 'cyclical downturn', 'macro headwinds'
                ],
                'phrases': [
                    r'market\s+(?:downturn|decline|weakness)',
                    r'economic\s+(?:slowdown|recession|headwinds)',
                    r'demand\s+(?:decline|weakness|slowdown)',
                    r'cyclical\s+(?:downturn|headwinds)',
                ]
            },
            'competitive': {
                'keywords': [
                    'competition', 'competitive pressure', 'market share loss',
                    'pricing pressure', 'commoditization', 'rivals', 'competitors'
                ],
                'phrases': [
                    r'competitive\s+(?:pressure|threat|challenge)',
                    r'market\s+share.*(?:loss|decline|pressure)',
                    r'pricing\s+pressure',
                    r'intense\s+competition',
                    r'competitor.*(?:threat|challenge)',
                ]
            },
            'regulatory': {
                'keywords': [
                    'regulation', 'regulatory risk', 'government intervention',
                    'policy changes', 'compliance', 'legal risk', 'antitrust'
                ],
                'phrases': [
                    r'regulatory\s+(?:risk|pressure|challenge)',
                    r'government\s+(?:intervention|regulation)',
                    r'antitrust\s+(?:concern|investigation)',
                    r'policy\s+(?:change|uncertainty)',
                    r'compliance\s+(?:risk|cost)',
                ]
            },
            'technological': {
                'keywords': [
                    'technology risk', 'obsolescence', 'disruption', 'innovation risk',
                    'technology shift', 'platform shift'
                ],
                'phrases': [
                    r'technology\s+(?:risk|disruption|shift)',
                    r'(?:technological|platform)\s+(?:obsolescence|disruption)',
                    r'innovation\s+risk',
                    r'disruptive\s+technology',
                ]
            },
            'financial': {
                'keywords': [
                    'financial risk', 'debt burden', 'liquidity risk', 'credit risk',
                    'cash flow risk', 'margin pressure', 'cost inflation'
                ],
                'phrases': [
                    r'financial\s+(?:risk|pressure|challenge)',
                    r'debt\s+(?:burden|concern|risk)',
                    r'cash\s+flow.*(?:risk|pressure|concern)',
                    r'margin\s+(?:pressure|compression)',
                    r'cost\s+(?:inflation|pressure)',
                ]
            }
        }
        
        # Define mitigation patterns
        self.mitigation_patterns = {
            'keywords': [
                'mitigate', 'address', 'counter', 'hedge', 'diversify', 'reduce risk',
                'contingency plan', 'risk management', 'strategic initiative'
            ],
            'phrases': [
                r'(?:plan|planning|strategy)\s+to\s+(?:address|mitigate|counter)',
                r'(?:diversif|hedge)(?:y|ying|ed).*(?:risk|exposure)',
                r'risk\s+(?:management|mitigation|reduction)',
                r'contingency\s+plan',
                r'strategic\s+(?:initiative|plan).*(?:address|mitigate)',
                r'taking\s+steps\s+to.*(?:address|mitigate|reduce)',
            ]
        }
        
        # Timeline keywords
        self.timeline_keywords = {
            'immediate': ['immediately', 'now', 'current', 'already', 'today'],
            'short-term': ['this quarter', 'next quarter', 'this year', 'near term', 'soon', 'within months'],
            'medium-term': ['next year', 'over the next', '12-18 months', 'medium term', '1-2 years'],
            'long-term': ['long term', 'multi-year', 'over the coming years', '3-5 years', 'decade']
        }
        
        # Severity indicators
        self.severity_indicators = {
            'critical': ['critical', 'severe', 'major threat', 'existential', 'catastrophic'],
            'high': ['significant', 'substantial', 'serious', 'major', 'considerable'],
            'medium': ['moderate', 'notable', 'meaningful', 'some concern'],
            'low': ['minor', 'limited', 'small', 'manageable', 'minimal']
        }

    # ============= LLM-POWERED ANALYSIS METHODS =============
    
    def _create_catalyst_analysis_prompt(self, article_content: str, company_ticker: str) -> List[Dict]:
        """Create Chain-of-Thought prompt for catalyst analysis."""
        return [
            {
                "role": "system",
                "content": f"""You are an expert financial analyst specializing in identifying growth catalysts for public companies. 
                You will analyze news articles to identify potential growth drivers that could positively impact a company's stock price and business performance.

                Your task is to:
                1. Read the article carefully
                2. Think step-by-step about potential growth catalysts
                3. Categorize each catalyst by type
                4. Assess confidence and timeline
                5. Provide clear reasoning

                Growth Catalyst Categories:
                - PRODUCT: New products, innovations, launches, technological breakthroughs
                - MARKET: Market expansion, new markets, growing demand, market opportunities
                - PARTNERSHIP: Strategic partnerships, deals, collaborations, major customer wins
                - TECHNOLOGY: R&D breakthroughs, patents, competitive advantages, technological moats
                - FINANCIAL: Revenue growth drivers, margin expansion, cost efficiencies, profitability improvements

                Timeline Categories:
                - IMMEDIATE: Already happening or within 3 months
                - SHORT_TERM: 3-12 months
                - MEDIUM_TERM: 1-3 years  
                - LONG_TERM: 3+ years

                Respond in JSON format with this structure:
                {{
                    "catalysts": [
                        {{
                            "type": "PRODUCT|MARKET|PARTNERSHIP|TECHNOLOGY|FINANCIAL",
                            "description": "Clear, concise description of the catalyst",
                            "confidence": 0.0-1.0,
                            "timeline": "IMMEDIATE|SHORT_TERM|MEDIUM_TERM|LONG_TERM",
                            "reasoning": "Step-by-step reasoning for why this is a catalyst",
                            "supporting_evidence": ["key quote 1", "key quote 2"],
                            "potential_impact": "Description of expected business impact"
                        }}
                    ]
                }}"""
            },
            {
                "role": "user", 
                "content": f"""Analyze this article about {company_ticker} for growth catalysts:

                ARTICLE CONTENT:
                {article_content}

                Please identify all potential growth catalysts using Chain-of-Thought reasoning. Be thorough but focus on the most significant catalysts with strong supporting evidence."""
            }
        ]

    def _create_risk_analysis_prompt(self, article_content: str, company_ticker: str) -> List[Dict]:
        """Create Chain-of-Thought prompt for risk analysis."""
        return [
            {
                "role": "system",
                "content": f"""You are an expert financial risk analyst specializing in identifying potential risks and threats that could negatively impact a company's stock price and business performance.

                Your task is to:
                1. Read the article carefully
                2. Think step-by-step about potential risks and threats
                3. Categorize each risk by type and severity
                4. Assess confidence and potential impact
                5. Provide clear reasoning

                Risk Categories:
                - MARKET: Market downturns, economic slowdowns, demand decline, cyclical risks
                - COMPETITIVE: Competition, pricing pressure, market share loss, disruption
                - REGULATORY: Government intervention, policy changes, compliance costs, antitrust
                - TECHNOLOGICAL: Technology disruption, obsolescence, innovation risks
                - FINANCIAL: Financial constraints, debt, cash flow, margin pressure

                Severity Levels:
                - CRITICAL: Existential threats, major business model risks
                - HIGH: Significant impact on revenue/profitability  
                - MEDIUM: Moderate impact, manageable challenges
                - LOW: Minor concerns, limited impact

                Respond in JSON format with this structure:
                {{
                    "risks": [
                        {{
                            "type": "MARKET|COMPETITIVE|REGULATORY|TECHNOLOGICAL|FINANCIAL",
                            "description": "Clear, concise description of the risk",
                            "severity": "CRITICAL|HIGH|MEDIUM|LOW",
                            "confidence": 0.0-1.0,
                            "reasoning": "Step-by-step reasoning for why this is a risk",
                            "supporting_evidence": ["key quote 1", "key quote 2"],
                            "potential_impact": "Description of expected negative impact",
                            "probability": "Assessment of likelihood this risk materializes"
                        }}
                    ]
                }}"""
            },
            {
                "role": "user",
                "content": f"""Analyze this article about {company_ticker} for potential risks and threats:

                ARTICLE CONTENT:
                {article_content}

                Please identify all potential risks using Chain-of-Thought reasoning. Focus on risks that could meaningfully impact the business."""
            }
        ]

    def _create_mitigation_analysis_prompt(self, article_content: str, company_ticker: str, identified_risks: List[Risk]) -> List[Dict]:
        """Create prompt for analyzing risk mitigation strategies."""
        risk_summary = "\n".join([f"- {risk.type}: {risk.description}" for risk in identified_risks])
        
        return [
            {
                "role": "system", 
                "content": f"""You are an expert business strategist analyzing how companies mitigate risks and what actions they are taking or planning to address identified threats.

                Your task is to:
                1. Review the article for mentions of mitigation strategies, company actions, or plans
                2. Match mitigation strategies to specific risks
                3. Assess the effectiveness of proposed/implemented mitigations
                4. Identify what the company is doing or planning to do

                Effectiveness Levels:
                - HIGH: Proven strategies, strong track record, comprehensive approach
                - MEDIUM: Reasonable strategies, some uncertainty, partial solutions
                - LOW: Unproven strategies, limited scope, questionable effectiveness

                Respond in JSON format with this structure:
                {{
                    "mitigations": [
                        {{
                            "risk_addressed": "Description of which risk this addresses",
                            "strategy": "Description of the mitigation strategy",
                            "company_action": "What the company is doing/planning to do",
                            "effectiveness": "HIGH|MEDIUM|LOW",
                            "confidence": 0.0-1.0,
                            "reasoning": "Why this mitigation strategy will work",
                            "supporting_evidence": ["key quote 1", "key quote 2"],
                            "timeline": "When this mitigation will be effective"
                        }}
                    ]
                }}"""
            },
            {
                "role": "user",
                "content": f"""Analyze this article about {company_ticker} for risk mitigation strategies and company actions:

                ARTICLE CONTENT:
                {article_content}

                IDENTIFIED RISKS TO ADDRESS:
                {risk_summary}

                Please identify any mitigation strategies, company actions, or plans mentioned in the article that address these or other risks."""
            }
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

    def analyze_article_with_llm(self, article: Dict, use_llm: bool = False) -> Tuple[List[Catalyst], List[Risk], List[Mitigation]]:
        """Analyze a single article using LLM for comprehensive insights."""
        if not use_llm or not LLM_AVAILABLE:
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

    def extract_catalysts(self, articles: List[Dict], use_llm: bool = False) -> List[Catalyst]:
        """Extract growth catalysts from articles using pattern matching and optionally LLM analysis."""
        catalysts = []
        
        # Pattern-based analysis (existing method)
        for article in articles:
            full_text = f"{article['title']} {article['text']}".lower()
            
            for catalyst_type, patterns in self.catalyst_patterns.items():
                # Check keywords
                keyword_matches = []
                for keyword in patterns['keywords']:
                    if keyword.lower() in full_text:
                        # Find sentences containing the keyword
                        sentences = self._extract_sentences_with_keyword(
                            article['text'], keyword
                        )
                        keyword_matches.extend(sentences)
                
                # Check regex patterns
                phrase_matches = []
                for pattern in patterns.get('phrases', []):
                    matches = re.finditer(pattern, full_text, re.IGNORECASE)
                    for match in matches:
                        # Extract surrounding context
                        context = self._extract_context(article['text'], match.start(), match.end())
                        phrase_matches.append(context)
                
                # If we found matches, create a catalyst
                all_matches = keyword_matches + phrase_matches
                if all_matches:
                    # Determine timeline
                    timeline = self._determine_timeline(article['text'])
                    
                    # Calculate confidence based on number of matches and context
                    confidence = self._calculate_catalyst_confidence(all_matches, catalyst_type)
                    
                    # Create description from best evidence
                    description = self._create_catalyst_description(catalyst_type, all_matches)
                    
                    catalyst = Catalyst(
                        type=catalyst_type,
                        description=description,
                        confidence=confidence,
                        supporting_evidence=all_matches[:3],  # Top 3 pieces of evidence
                        articles_mentioned=[article['file_name']],
                        timeline=timeline
                    )
                    catalysts.append(catalyst)
        
        # LLM-based analysis (enhanced analysis)
        if use_llm:
            print(f"[info] Using LLM analysis for {len(articles)} articles...")
            for article in articles:
                llm_catalysts, _, _ = self.analyze_article_with_llm(article, use_llm=True)
                catalysts.extend(llm_catalysts)
        
        # Merge similar catalysts from both methods
        return self._merge_similar_catalysts(catalysts)

    def extract_risks(self, articles: List[Dict], use_llm: bool = False) -> List[Risk]:
        """Extract risks from articles using pattern matching and optionally LLM analysis."""
        risks = []
        
        # Pattern-based analysis (existing method)
        for article in articles:
            full_text = f"{article['title']} {article['text']}".lower()
            
            for risk_type, patterns in self.risk_patterns.items():
                # Check keywords and phrases
                keyword_matches = []
                for keyword in patterns['keywords']:
                    if keyword.lower() in full_text:
                        sentences = self._extract_sentences_with_keyword(
                            article['text'], keyword
                        )
                        keyword_matches.extend(sentences)
                
                phrase_matches = []
                for pattern in patterns.get('phrases', []):
                    matches = re.finditer(pattern, full_text, re.IGNORECASE)
                    for match in matches:
                        context = self._extract_context(article['text'], match.start(), match.end())
                        phrase_matches.append(context)
                
                all_matches = keyword_matches + phrase_matches
                if all_matches:
                    # Determine severity
                    severity = self._determine_severity(article['text'])
                    
                    # Calculate confidence
                    confidence = self._calculate_risk_confidence(all_matches, risk_type)
                    
                    # Create description
                    description = self._create_risk_description(risk_type, all_matches)
                    
                    # Determine potential impact
                    potential_impact = self._determine_potential_impact(article['text'], all_matches)
                    
                    risk = Risk(
                        type=risk_type,
                        description=description,
                        severity=severity,
                        confidence=confidence,
                        supporting_evidence=all_matches[:3],
                        articles_mentioned=[article['file_name']],
                        potential_impact=potential_impact
                    )
                    risks.append(risk)
        
        # LLM-based analysis (enhanced analysis)
        if use_llm:
            for article in articles:
                _, llm_risks, _ = self.analyze_article_with_llm(article, use_llm=True)
                risks.extend(llm_risks)
        
        return self._merge_similar_risks(risks)

    def extract_mitigations(self, articles: List[Dict], identified_risks: List[Risk], use_llm: bool = False) -> List[Mitigation]:
        """Extract risk mitigation strategies using pattern matching and optionally LLM analysis."""
        mitigations = []
        
        # Pattern-based analysis (existing method)
        for article in articles:
            full_text = f"{article['title']} {article['text']}".lower()
            
            # Look for mitigation keywords and phrases
            mitigation_evidence = []
            
            for keyword in self.mitigation_patterns['keywords']:
                if keyword.lower() in full_text:
                    sentences = self._extract_sentences_with_keyword(
                        article['text'], keyword
                    )
                    mitigation_evidence.extend(sentences)
            
            for pattern in self.mitigation_patterns['phrases']:
                matches = re.finditer(pattern, full_text, re.IGNORECASE)
                for match in matches:
                    context = self._extract_context(article['text'], match.start(), match.end())
                    mitigation_evidence.append(context)
            
            if mitigation_evidence:
                # Try to match mitigations to specific risks
                for risk in identified_risks:
                    risk_keywords = self._extract_risk_keywords(risk.description)
                    
                    # Check if mitigation evidence mentions risk-related terms
                    relevance_score = 0
                    relevant_evidence = []
                    
                    for evidence in mitigation_evidence:
                        evidence_lower = evidence.lower()
                        for risk_keyword in risk_keywords:
                            if risk_keyword.lower() in evidence_lower:
                                relevance_score += 1
                                relevant_evidence.append(evidence)
                                break
                    
                    if relevance_score > 0 or len(mitigation_evidence) > 2:
                        # Create mitigation strategy
                        strategy = self._create_mitigation_strategy(mitigation_evidence)
                        confidence = min(0.9, relevance_score * 0.3 + len(relevant_evidence) * 0.2)
                        effectiveness = self._determine_effectiveness(mitigation_evidence)
                        
                        mitigation = Mitigation(
                            risk_addressed=risk.description,
                            strategy=strategy,
                            confidence=confidence,
                            supporting_evidence=relevant_evidence[:3] if relevant_evidence else mitigation_evidence[:3],
                            articles_mentioned=[article['file_name']],
                            effectiveness=effectiveness
                        )
                        mitigations.append(mitigation)
        
        # LLM-based analysis (enhanced analysis)
        if use_llm:
            for article in articles:
                _, _, llm_mitigations = self.analyze_article_with_llm(article, use_llm=True)
                mitigations.extend(llm_mitigations)
        
        return self._merge_similar_mitigations(mitigations)

    def _extract_sentences_with_keyword(self, text: str, keyword: str) -> List[str]:
        """Extract sentences containing a specific keyword."""
        sentences = re.split(r'[.!?]+', text)
        matching_sentences = []
        
        for sentence in sentences:
            if keyword.lower() in sentence.lower() and len(sentence.strip()) > 20:
                matching_sentences.append(sentence.strip())
        
        return matching_sentences[:2]  # Limit to 2 sentences per keyword

    def _extract_context(self, text: str, start: int, end: int, context_size: int = 100) -> str:
        """Extract context around a matched pattern."""
        context_start = max(0, start - context_size)
        context_end = min(len(text), end + context_size)
        return text[context_start:context_end].strip()

    def _determine_timeline(self, text: str) -> str:
        """Determine timeline based on text analysis."""
        text_lower = text.lower()
        
        for timeline, keywords in self.timeline_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return timeline
        
        return 'medium-term'  # Default

    def _determine_severity(self, text: str) -> str:
        """Determine risk severity based on text analysis."""
        text_lower = text.lower()
        
        for severity, indicators in self.severity_indicators.items():
            for indicator in indicators:
                if indicator in text_lower:
                    return severity
        
        return 'medium'  # Default

    def _calculate_catalyst_confidence(self, matches: List[str], catalyst_type: str) -> float:
        """Calculate confidence score for catalyst."""
        base_confidence = min(0.9, len(matches) * 0.2)
        
        # Boost confidence for specific catalyst types with strong evidence
        if catalyst_type in ['product', 'partnership'] and len(matches) >= 2:
            base_confidence += 0.1
        
        return max(0.1, min(1.0, base_confidence))

    def _calculate_risk_confidence(self, matches: List[str], risk_type: str) -> float:
        """Calculate confidence score for risk."""
        base_confidence = min(0.8, len(matches) * 0.25)
        return max(0.1, min(1.0, base_confidence))

    def _create_catalyst_description(self, catalyst_type: str, matches: List[str]) -> str:
        """Create a description for the catalyst."""
        if not matches:
            return f"Potential {catalyst_type} catalyst identified"
        
        # Use the most relevant match as basis for description
        best_match = max(matches, key=len)
        
        # Clean and truncate
        description = re.sub(r'\s+', ' ', best_match).strip()
        if len(description) > 150:
            description = description[:150] + "..."
        
        return description

    def _create_risk_description(self, risk_type: str, matches: List[str]) -> str:
        """Create a description for the risk."""
        if not matches:
            return f"Potential {risk_type} risk identified"
        
        best_match = max(matches, key=len)
        description = re.sub(r'\s+', ' ', best_match).strip()
        if len(description) > 150:
            description = description[:150] + "..."
        
        return description

    def _determine_potential_impact(self, text: str, matches: List[str]) -> str:
        """Determine potential impact of risk."""
        combined_text = (text + " " + " ".join(matches)).lower()
        
        # Look for impact indicators
        if any(word in combined_text for word in ['revenue decline', 'profit loss', 'market share loss']):
            return 'High financial impact expected'
        elif any(word in combined_text for word in ['margin pressure', 'cost increase', 'efficiency loss']):
            return 'Moderate financial impact expected'
        else:
            return 'Impact assessment required'

    def _extract_risk_keywords(self, risk_description: str) -> List[str]:
        """Extract key terms from risk description for matching."""
        # Simple keyword extraction
        words = re.findall(r'\b\w+\b', risk_description.lower())
        # Filter out common words
        stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were'}
        keywords = [word for word in words if len(word) > 3 and word not in stopwords]
        return keywords[:5]  # Top 5 keywords

    def _create_mitigation_strategy(self, evidence: List[str]) -> str:
        """Create mitigation strategy description."""
        if not evidence:
            return "Mitigation strategy identified"
        
        # Combine evidence and create coherent strategy
        best_evidence = max(evidence, key=len)
        strategy = re.sub(r'\s+', ' ', best_evidence).strip()
        if len(strategy) > 200:
            strategy = strategy[:200] + "..."
        
        return strategy

    def _determine_effectiveness(self, evidence: List[str]) -> str:
        """Determine effectiveness of mitigation strategy."""
        combined_evidence = " ".join(evidence).lower()
        
        if any(word in combined_evidence for word in ['proven', 'successful', 'effective', 'strong track record']):
            return 'high'
        elif any(word in combined_evidence for word in ['plan', 'strategy', 'initiative', 'working on']):
            return 'medium'
        else:
            return 'low'

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
                                mitigations: List[Mitigation], output_file: pathlib.Path, use_llm: bool = False):
        """Generate comprehensive screening report with LLM insights."""
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"# {self.ticker} AI-Enhanced Stock Screening Analysis\n\n")
            f.write(f"**Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"**Analysis Method:** {'LLM-Enhanced Pattern Analysis' if use_llm else 'Traditional Pattern Analysis'}\n\n")
            
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
                    
                    if use_llm and catalyst.llm_reasoning:
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
                    
                    if use_llm and risk.llm_reasoning:
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
                    
                    if use_llm and mitigation.llm_reasoning:
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
            
            # Add cost information if LLM was used
            if use_llm and self.llm_call_count > 0:
                f.write(f"\n## 💰 LLM Analysis Cost Summary\n\n")
                f.write(f"**Total LLM Calls:** {self.llm_call_count}\n")
                f.write(f"**Total Cost:** ${self.total_llm_cost:.6f} USD\n")
                f.write(f"**Average Cost per Call:** ${self.total_llm_cost/self.llm_call_count:.6f} USD\n\n")
            
            f.write(f"\n---\n*Analysis completed using {len(catalysts + risks + mitigations)} insights from filtered articles.*")
            if use_llm and self.llm_call_count > 0:
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
    parser = argparse.ArgumentParser(description="AI-Enhanced Stock Screening: Analyze filtered articles for investment insights")
    parser.add_argument("--ticker", required=True, help="Stock ticker, e.g. NVDA")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="Minimum confidence threshold (0.0-1.0)")
    parser.add_argument("--output-report", action="store_true", help="Generate detailed screening report")
    parser.add_argument("--save-data", action="store_true", help="Save structured data as JSON")
    parser.add_argument("--detailed-analysis", action="store_true", help="Include detailed analysis in output")
    parser.add_argument("--use-llm", action="store_true", help="Enable LLM-powered analysis (requires OpenAI API key)")
    
    args = parser.parse_args()
    
    # Initialize screener
    screener = ArticleScreener(args.ticker)
    
    # Load filtered articles
    print(f"[info] Loading filtered articles for {args.ticker}")
    articles = screener.load_filtered_articles()
    
    if not articles:
        print("[warn] No filtered articles found")
        return
    
    analysis_mode = "LLM-Enhanced" if args.use_llm else "Pattern-Based"
    print(f"[info] Analyzing {len(articles)} filtered articles using {analysis_mode} analysis")
    
    if args.use_llm:
        if not LLM_AVAILABLE:
            print("[error] LLM functionality not available. Please check that llms.py is properly configured.")
            return
        print("[info] 🤖 LLM analysis enabled - this will provide deeper insights but take longer and cost API credits")
    
    # Extract insights
    print("[info] Extracting growth catalysts...")
    catalysts = screener.extract_catalysts(articles, use_llm=args.use_llm)
    catalysts = [c for c in catalysts if c.confidence >= args.min_confidence]
    
    print("[info] Identifying risks...")
    risks = screener.extract_risks(articles, use_llm=args.use_llm)
    risks = [r for r in risks if r.confidence >= args.min_confidence]
    
    print("[info] Analyzing mitigation strategies...")
    mitigations = screener.extract_mitigations(articles, risks, use_llm=args.use_llm)
    mitigations = [m for m in mitigations if m.confidence >= args.min_confidence]
    
    # Display summary
    print(f"\n[results] Analysis complete:")
    print(f"  Growth Catalysts: {len(catalysts)}")
    print(f"  Risks Identified: {len(risks)}")
    print(f"  Mitigation Strategies: {len(mitigations)}")
    
    # Display LLM cost information if LLM was used
    if args.use_llm and screener.llm_call_count > 0:
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
        screener.generate_screening_report(catalysts, risks, mitigations, report_file, use_llm=args.use_llm)
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
