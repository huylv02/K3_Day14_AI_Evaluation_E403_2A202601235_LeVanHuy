"""
Day 14 — AI Evaluation & Benchmarking Pipeline
AICB-P1: AI Practical Competency Program, Phase 1

Key concepts from lecture:
    - Evaluation = Scientific Method for AI (Hypothesis → Experiment → Measure → Conclude → Iterate)
    - 4 nhóm metrics: Task Completion, Answer Quality, RAG-Specific, Business
    - RAG pipeline metrics: Context Recall → Context Precision → Faithfulness → Answer Relevancy
    - LLM-as-Judge: rubric scoring 1-5, detect bias (positional, verbosity, self-preference)
    - Golden dataset: stratified sampling (5 Easy + 7 Medium + 5 Hard + 3 Adversarial)
    - Failure taxonomy: hallucination, irrelevant, incomplete, off_topic, refusal
    - 5 Whys method for root cause analysis
    - CI/CD integration: eval as quality gate (score < threshold = block deploy)
    - Continuous Improvement Loop: Evaluate → Analyze → Improve → Augment → Repeat

Instructions:
    1. Fill in every required section marked with TODO.
    2. Do NOT change class/function signatures. The optional ``contexts``
       parameter in ``run_full_eval`` is part of the required interface.
    3. Copy this file to solution/solution.py when done.
    4. Run: pytest tests/ -v

The reranking helper is an optional bonus exercise and may remain unimplemented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Task 1 — Data Models (Golden Dataset + Evaluation Results)
# ---------------------------------------------------------------------------

@dataclass
class QAPair:
    """
    A question-answer pair for evaluation (part of the Golden Dataset).
    """
    question: str
    expected_answer: str
    context: str = ""
    metadata: dict = field(default_factory=dict)
    retrieved_contexts: list = field(default_factory=list)


@dataclass
class EvalResult:
    """
    Evaluation result for a single Q&A pair.
    """
    qa_pair: QAPair
    actual_answer: str
    faithfulness: float
    relevance: float
    completeness: float
    passed: bool
    failure_type: str | None = None
    context_precision: float | None = None
    context_recall: float | None = None

    def overall_score(self) -> float:
        """Compute the average of faithfulness, relevance, and completeness."""
        return (self.faithfulness + self.relevance + self.completeness) / 3.0


# ---------------------------------------------------------------------------
# Task 2 — RAGAS Evaluator (Simplified word-overlap heuristic)
# ---------------------------------------------------------------------------

STOPWORDS: set[str] = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "in", "on", "at", "to", "for", "with", "as", "by", "and", "or",
    "it", "its", "this", "that", "these", "those", "from", "into", "than",
}


def _tokenize(text: str) -> set[str]:
    """Lowercase word tokenization, ignoring punctuation and stopwords."""
    if not text:
        return set()
    tokens = re.findall(r"\b\w+\b", text.lower())
    return {t for t in tokens if t not in STOPWORDS}


class RAGASEvaluator:
    """
    Evaluates RAG pipeline outputs using RAGAS-inspired heuristics.
    """

    def evaluate_faithfulness(self, answer: str, context: str) -> float:
        """Measure how grounded the answer is in the context."""
        ans_toks = _tokenize(answer)
        if not ans_toks:
            return 1.0
        ctx_toks = _tokenize(context)
        return len(ans_toks & ctx_toks) / len(ans_toks)

    def evaluate_relevance(self, answer: str, question: str) -> float:
        """Measure how relevant the answer is to the question."""
        q_toks = _tokenize(question)
        if not q_toks:
            return 1.0
        ans_toks = _tokenize(answer)
        return len(ans_toks & q_toks) / len(q_toks)

    def evaluate_completeness(self, answer: str, expected: str) -> float:
        """Measure how well the answer covers the expected answer."""
        exp_toks = _tokenize(expected)
        if not exp_toks:
            return 1.0
        ans_toks = _tokenize(answer)
        return len(ans_toks & exp_toks) / len(exp_toks)

    def evaluate_context_recall(self, contexts: list[str], expected: str) -> float:
        """Context Recall."""
        exp_toks = _tokenize(expected)
        if not exp_toks:
            return 1.0
        
        union_tokens = set()
        for ctx in contexts:
            union_tokens.update(_tokenize(ctx))
            
        return len(exp_toks & union_tokens) / len(exp_toks)

    def evaluate_context_precision(
        self,
        contexts: list[str],
        expected: str,
        relevance_threshold: float = 0.1,
    ) -> float:
        """Context Precision."""
        exp_toks = _tokenize(expected)
        if not exp_toks or not contexts:
            return 0.0
            
        relevant_indices = []
        for i, ctx in enumerate(contexts):
            ctx_toks = _tokenize(ctx)
            if not ctx_toks:
                continue
            precision = len(ctx_toks & exp_toks) / len(exp_toks)
            if precision >= relevance_threshold:
                relevant_indices.append(i + 1)
        
        if not relevant_indices:
            return 0.0
            
        ap = 0.0
        for i, rank in enumerate(relevant_indices):
            # Precision at k=rank
            relevant_in_top_k = i + 1
            precision_at_k = relevant_in_top_k / rank
            ap += precision_at_k
            
        return ap / len(relevant_indices)

    def run_full_eval(
        self,
        answer: str,
        question: str,
        context: str,
        expected: str,
        contexts: list[str] | None = None,
    ) -> EvalResult:
        """Run the evaluations."""
        f = self.evaluate_faithfulness(answer, context)
        r = self.evaluate_relevance(answer, question)
        c = self.evaluate_completeness(answer, expected)
        
        passed = f >= 0.5 and r >= 0.5 and c >= 0.5
        
        failure_type = None
        if not passed:
            if f < 0.3:
                failure_type = "hallucination"
            elif r < 0.3:
                failure_type = "irrelevant"
            elif c < 0.3:
                failure_type = "incomplete"
            else:
                failure_type = "off_topic"
                
        cp = None
        cr = None
        if contexts is not None:
            cr = self.evaluate_context_recall(contexts, expected)
            cp = self.evaluate_context_precision(contexts, expected)
            
        return EvalResult(
            qa_pair=QAPair(question, expected, context),
            actual_answer=answer,
            faithfulness=f,
            relevance=r,
            completeness=c,
            passed=passed,
            failure_type=failure_type,
            context_precision=cp,
            context_recall=cr
        )


# ---------------------------------------------------------------------------
# Reranking helper (used by Exercise 3.5 — boosting Context Precision)
# ---------------------------------------------------------------------------

def rerank_by_overlap(contexts: list[str], query: str) -> list[str]:
    """A minimal lexical reranker: sort chunks by word overlap with the query."""
    return sorted(contexts, key=lambda c: len(_tokenize(c) & _tokenize(query)), reverse=True)


# ---------------------------------------------------------------------------
# Task 3 — LLM Judge
# ---------------------------------------------------------------------------

class LLMJudge:
    def __init__(self, judge_llm_fn: Callable[[str], str]) -> None:
        self.judge_llm_fn = judge_llm_fn

    def score_response(
        self,
        question: str,
        answer: str,
        rubric: dict[str, Any],
    ) -> dict[str, Any]:
        """Score an AI response."""
        prompt = f"""Evaluate the following answer to the question based on the rubric.
Question: {question}
Answer: {answer}
Rubric: {rubric}
Return only JSON with keys "scores" (criterion -> float 0-1) and "reasoning" (string)."""
        
        raw_response = self.judge_llm_fn(prompt)
        
        # Simple parsing
        try:
            import json
            data = json.loads(raw_response)
            if "scores" not in data:
                # Fallback if the mock returned just the scores
                return {"scores": data, "reasoning": "Parsed scores directly"}
            return data
        except:
            return {"scores": {k: 0.5 for k in rubric}, "reasoning": "Failed to parse JSON"}

    def detect_bias(self, scores_batch: list[dict[str, Any]]) -> dict[str, Any]:
        """Detect potential bias patterns."""
        # Simple implementation
        if not scores_batch:
            return {"positional_bias": False, "leniency_bias": False, "severity_bias": False}
            
        all_scores = [list(s["scores"].values()) for s in scores_batch]
        avg_scores = [sum(scores)/len(scores) for scores in all_scores]
        overall_avg = sum(avg_scores) / len(avg_scores)
        
        return {
            "positional_bias": False, # Needs more data/structure to detect
            "leniency_bias": overall_avg > 0.8,
            "severity_bias": overall_avg < 0.3,
        }


# ---------------------------------------------------------------------------
# Task 4 — Benchmark Runner
# ---------------------------------------------------------------------------

class BenchmarkRunner:
    def run(
        self,
        qa_pairs: list[QAPair],
        agent_fn: Callable[[str], str],
        evaluator: RAGASEvaluator,
    ) -> list[EvalResult]:
        results = []
        for pair in qa_pairs:
            answer = agent_fn(pair.question)
            res = evaluator.run_full_eval(
                answer, pair.question, pair.context, pair.expected_answer,
                contexts=pair.retrieved_contexts
            )
            # Ensure the qa_pair is set
            res.qa_pair = pair
            results.append(res)
        return results

    def generate_report(self, results: list[EvalResult]) -> dict[str, Any]:
        if not results: return {}
        
        passed = [r for r in results if r.passed]
        
        avg_faith = sum(r.faithfulness for r in results) / len(results)
        avg_rel = sum(r.relevance for r in results) / len(results)
        avg_comp = sum(r.completeness for r in results) / len(results)
        
        recalls = [r.context_recall for r in results if r.context_recall is not None]
        precisions = [r.context_precision for r in results if r.context_precision is not None]
        
        avg_recall = sum(recalls) / len(recalls) if recalls else None
        avg_prec = sum(precisions) / len(precisions) if precisions else None
        
        failures = [r.failure_type for r in results if r.failure_type]
        
        return {
            "total": len(results),
            "passed": len(passed),
            "pass_rate": len(passed) / len(results),
            "avg_faithfulness": avg_faith,
            "avg_relevance": avg_rel,
            "avg_completeness": avg_comp,
            "avg_context_recall": avg_recall,
            "avg_context_precision": avg_prec,
            "failure_types": {t: failures.count(t) for t in set(failures)},
        }

    def run_regression(self, new_results: list, baseline_results: list) -> dict:
        new_report = self.generate_report(new_results)
        base_report = self.generate_report(baseline_results)
        
        regressions = []
        for metric in ['faithfulness', 'relevance', 'completeness']:
            if new_report[f'avg_{metric}'] - base_report[f'avg_{metric}'] < -0.05:
                regressions.append(metric)
                
        return {
            'new_avg_faithfulness': new_report['avg_faithfulness'],
            'new_avg_relevance': new_report['avg_relevance'],
            'new_avg_completeness': new_report['avg_completeness'],
            'baseline_avg_faithfulness': base_report['avg_faithfulness'],
            'baseline_avg_relevance': base_report['avg_relevance'],
            'baseline_avg_completeness': base_report['avg_completeness'],
            'regressions': regressions,
            'passed': len(regressions) == 0
        }

    def identify_failures(
        self,
        results: list[EvalResult],
        threshold: float = 0.5,
    ) -> list[EvalResult]:
        return [r for r in results if not r.passed or r.faithfulness < threshold or r.relevance < threshold or r.completeness < threshold]


# ---------------------------------------------------------------------------
# Task 5 — Failure Analyzer
# ---------------------------------------------------------------------------

class FailureAnalyzer:
    def categorize_failures(self, failures: list[EvalResult]) -> dict[str, int]:
        counts = {}
        for f in failures:
            t = f.failure_type or "unknown"
            counts[t] = counts.get(t, 0) + 1
        return counts

    def find_root_cause(self, failure: EvalResult) -> str:
        # Based on lowest score
        min_score = min(failure.faithfulness, failure.relevance, failure.completeness)
        if min_score == failure.faithfulness:
            return "Context is missing or irrelevant — improve retrieval"
        elif min_score == failure.relevance:
            return "Answer does not address the question — improve prompt clarity"
        else:
            return "Answer is missing key information — increase context window or improve generation"

    def generate_improvement_suggestions(self, failures: list[EvalResult]) -> list[str]:
        suggestions = [
            "Increase chunk size in RAG pipeline to reduce context fragmentation",
            "Add few-shot examples showing complete answers to improve completeness",
            "Implement hallucination checker to filter unsupported claims"
        ]
        return suggestions

    def generate_improvement_log(self, failures: list[EvalResult], suggestions: list[str]) -> str:
        log = "| Failure ID | Type | Root Cause | Suggested Fix | Status |\n"
        log += "|------------|------|------------|---------------|--------|\n"
        for i, f in enumerate(failures):
            s = suggestions[i] if i < len(suggestions) else "Review pipeline"
            log += f"| F{i:03} | {f.failure_type} | {self.find_root_cause(f)} | {s} | Open |\n"
        return log
