#!/usr/bin/env python3
"""
Experiment 4: Qualitative Case Studies
Extracts detailed case study data from existing analyses or runs fresh analyses.
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import glob


class CaseStudyExtractor:
    """Extract detailed case study information from analysis artifacts."""
    
    def __init__(self, base_dir: str = "data"):
        self.base_dir = Path(base_dir)
        self.results_dir = Path("experiments/results/experiment_4")
        self.results_dir.mkdir(parents=True, exist_ok=True)
    
    def find_latest_analysis(self, ticker: str) -> Optional[Path]:
        """Find the most recent complete analysis for a ticker."""
        # Search in all user directories
        pattern = f"{self.base_dir}/*/sessions/{ticker}/*.json"
        session_files = glob.glob(pattern)
        
        if not session_files:
            print(f"  ❌ No analysis found for {ticker}")
            return None
        
        # Find the file with the largest size (most complete)
        # and filter out experiment runs
        non_experiment_files = [f for f in session_files if 'experiment3' not in f and 'repro' not in f]
        if non_experiment_files:
            session_files = non_experiment_files
        
        best = max(session_files, key=lambda f: os.path.getsize(f))
        print(f"  ✅ Found analysis: {best} ({os.path.getsize(best)} bytes)")
        return Path(best)
    
    def load_session_data(self, session_path: Path) -> Optional[Dict]:
        """Load session JSON data."""
        try:
            with open(session_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"  ❌ Error loading {session_path}: {e}")
            return None
    
    def find_screening_data(self, ticker: str, timestamp: str) -> Optional[Dict]:
        """Find screening data for a specific analysis."""
        pattern = f"{self.base_dir}/*/{ticker}/{timestamp}/screened/screening_data.json"
        files = glob.glob(pattern)
        
        if files:
            try:
                with open(files[0], 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"  ⚠️  Warning: Could not load screening data: {e}")
        return None
    
    def find_financial_model(self, ticker: str, timestamp: str) -> Optional[Dict]:
        """Find financial model data."""
        pattern = f"{self.base_dir}/*/{ticker}/{timestamp}/models/*_financial_model_computed_values.json"
        files = glob.glob(pattern)
        
        if files:
            try:
                with open(files[0], 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"  ⚠️  Warning: Could not load financial model: {e}")
        return None
    
    def find_report(self, ticker: str, timestamp: str) -> Optional[str]:
        """Find generated report markdown."""
        pattern = f"{self.base_dir}/*/{ticker}/{timestamp}/reports/*.md"
        files = glob.glob(pattern)
        
        if files:
            try:
                with open(files[0], 'r') as f:
                    return f.read()
            except Exception as e:
                print(f"  ⚠️  Warning: Could not load report: {e}")
        return None
    
    def extract_case_study(self, ticker: str) -> Optional[Dict]:
        """Extract complete case study data for a ticker."""
        print(f"\n{'='*60}")
        print(f"EXTRACTING CASE STUDY: {ticker}")
        print(f"{'='*60}")
        
        # Find latest analysis
        session_path = self.find_latest_analysis(ticker)
        if not session_path:
            return None
        
        # Load session data
        session_data = self.load_session_data(session_path)
        if not session_data:
            return None
        
        # Get first conversation (main analysis)
        if not session_data.get('conversation_history'):
            print(f"  ❌ No conversation history found")
            return None
        
        conversation = session_data['conversation_history'][0]
        
        # Extract timestamp for finding related files
        timestamp = conversation.get('timestamp', '').split('T')[0]
        # Try to find folder by number
        pattern = f"{self.base_dir}/*/{ticker}/*"
        ticker_folders = glob.glob(pattern)
        if ticker_folders:
            # Get most recent folder number
            folder_nums = [f.split('/')[-1] for f in ticker_folders if f.split('/')[-1].isdigit()]
            if folder_nums:
                timestamp = max(folder_nums)
        
        # Load additional data
        screening_data = self.find_screening_data(ticker, timestamp)
        financial_model = self.find_financial_model(ticker, timestamp)
        report_text = self.find_report(ticker, timestamp)
        
        # Structure the case study
        case_study = {
            "ticker": ticker,
            "company_name": session_data.get('company_name', ticker),
            "analysis_date": session_data.get('created_at'),
            "session_file": str(session_path),
            
            # Query and routing
            "user_query": conversation.get('user_query'),
            "agents_executed": conversation.get('routing_decisions', []),
            "completion_status": conversation.get('completion_status'),
            
            # Statistics
            "statistics": conversation.get('statistics', {}),
            
            # News analysis
            "news_analysis": {
                "articles_analyzed": conversation.get('analysis_results', {}).get('news_summary', {}).get('articles_analyzed', 0),
                "overall_sentiment": conversation.get('analysis_results', {}).get('news_summary', {}).get('overall_sentiment'),
                "catalysts_count": conversation.get('analysis_results', {}).get('news_summary', {}).get('catalysts_count', 0),
                "risks_count": conversation.get('analysis_results', {}).get('news_summary', {}).get('risks_count', 0),
                "top_catalysts": conversation.get('analysis_results', {}).get('news_summary', {}).get('top_catalysts', [])[:3],
                "top_risks": conversation.get('analysis_results', {}).get('news_summary', {}).get('top_risks', [])[:3],
            },
            
            # Valuation
            "valuation": conversation.get('analysis_results', {}).get('valuation', {}),
            
            # Detailed screening data (if available)
            "detailed_screening": None,
            "financial_model": None,
            "report_excerpt": None,
        }
        
        # Add detailed data if available
        if screening_data:
            case_study["detailed_screening"] = {
                "timestamp": screening_data.get('timestamp'),
                "analysis_summary": screening_data.get('analysis_summary'),
                "catalysts": screening_data.get('catalysts', [])[:5],  # Top 5
                "risks": screening_data.get('risks', [])[:5],  # Top 5
            }
            print(f"  ✅ Loaded screening data: {len(screening_data.get('catalysts', []))} catalysts, {len(screening_data.get('risks', []))} risks")
        
        if financial_model:
            case_study["financial_model"] = {
                "wacc": financial_model.get('wacc'),
                "terminal_value": financial_model.get('terminal_value'),
                "enterprise_value": financial_model.get('enterprise_value'),
                "equity_value": financial_model.get('equity_value'),
                "fair_value_per_share": financial_model.get('fair_value_per_share'),
                "fcf_projections": financial_model.get('fcf', {}).get('projected_fcf', [])[:5],  # 5 years
            }
            print(f"  ✅ Loaded financial model: Fair Value = ${financial_model.get('fair_value_per_share', 0):.2f}")
        
        if report_text:
            # Extract executive summary (first 500 chars of report)
            lines = report_text.split('\n')
            summary_lines = []
            for line in lines[5:30]:  # Skip header, take next 25 lines
                if line.strip():
                    summary_lines.append(line)
                if len('\n'.join(summary_lines)) > 500:
                    break
            case_study["report_excerpt"] = '\n'.join(summary_lines[:10])
            print(f"  ✅ Loaded report (excerpt extracted)")
        
        print(f"\n  📊 CASE STUDY SUMMARY:")
        print(f"     - Duration: {case_study['statistics'].get('duration', 0):.1f}s")
        print(f"     - Agents: {case_study['statistics'].get('agents_count', 0)}")
        print(f"     - Articles: {case_study['news_analysis']['articles_analyzed']}")
        print(f"     - Sentiment: {case_study['news_analysis']['overall_sentiment']}")
        print(f"     - Fair Value: ${case_study['valuation'].get('fair_value', 0):.2f}")
        print(f"     - Current Price: ${case_study['valuation'].get('current_price', 0):.2f}")
        print(f"     - Upside: {case_study['valuation'].get('upside_downside', 0)*100:.1f}%")
        
        return case_study
    
    def save_case_study(self, case_study: Dict, filename: str):
        """Save case study to JSON file."""
        output_path = self.results_dir / filename
        with open(output_path, 'w') as f:
            json.dump(case_study, f, indent=2)
        print(f"\n  💾 Saved to: {output_path}")
        return output_path


def main():
    """Main execution function."""
    print("="*70)
    print("EXPERIMENT 4: QUALITATIVE CASE STUDIES")
    print("="*70)
    print("\nExtracting detailed case study data from existing analyses...")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    extractor = CaseStudyExtractor()
    
    # Target companies for case studies
    companies = ["META", "NVDA", "AAPL"]
    
    case_studies = []
    successful = 0
    
    for ticker in companies:
        case_study = extractor.extract_case_study(ticker)
        if case_study:
            filename = f"case_study_{ticker.lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            extractor.save_case_study(case_study, filename)
            case_studies.append(case_study)
            successful += 1
    
    # Create summary
    summary = {
        "experiment": "Experiment 4 - Qualitative Case Studies",
        "timestamp": datetime.now().isoformat(),
        "companies_analyzed": successful,
        "companies_target": len(companies),
        "case_studies": [
            {
                "ticker": cs["ticker"],
                "company_name": cs["company_name"],
                "articles_analyzed": cs["news_analysis"]["articles_analyzed"],
                "sentiment": cs["news_analysis"]["overall_sentiment"],
                "fair_value": cs["valuation"].get("fair_value"),
                "upside": cs["valuation"].get("upside_downside"),
            }
            for cs in case_studies
        ]
    }
    
    summary_path = extractor.results_dir / f"experiment_4_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n{'='*70}")
    print("EXPERIMENT 4 COMPLETE")
    print(f"{'='*70}")
    print(f"✅ Successfully extracted {successful}/{len(companies)} case studies")
    print(f"📊 Summary saved to: {summary_path}")
    print(f"\nNext step: Run analyze_experiment_4.py to generate report")


if __name__ == "__main__":
    main()
