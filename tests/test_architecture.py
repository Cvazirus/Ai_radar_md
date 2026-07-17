"""Architecture tests for PipelineOrchestrator."""
import ast
import pytest


class TestPipelineOrchestratorArchitecture:
    """Verify PipelineOrchestrator is pure orchestration."""
    
    def test_no_db_commit_in_step_methods(self):
        """Step methods should not have db.commit() - only PipelineRun tracking should commit."""
        with open("app/services/pipeline_orchestrator.py", "r") as f:
            tree = ast.parse(f.read())
        
        # Find all step methods and check they don't have commits
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if node.name.startswith("_step_"):
                    commit_in_step = []
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call):
                            if isinstance(child.func, ast.Attribute):
                                if child.func.attr == "commit":
                                    commit_in_step.append(child.lineno)
                    assert len(commit_in_step) == 0, (
                        f"Step {node.name} has db.commit() at lines {commit_in_step}. "
                        f"Step methods should delegate to services."
                    )
    
    def test_no_db_add_outside_pipeline_run(self):
        """Orchestrator should only add PipelineRun, not domain objects."""
        with open("app/services/pipeline_orchestrator.py", "r") as f:
            content = f.read()
        
        # Check that db.add is only used for PipelineRun
        lines = content.split('\n')
        add_calls = []
        for i, line in enumerate(lines, 1):
            if 'db.add(' in line and 'pipeline_run' not in line:
                add_calls.append(i)
        
        assert len(add_calls) == 0, f"Found db.add() calls for non-PipelineRun at lines {add_calls}"
    
    def test_no_validate_source_claims_import(self):
        """Orchestrator should not import claim validation directly."""
        with open("app/services/pipeline_orchestrator.py", "r") as f:
            content = f.read()
        
        assert "validate_source_claims" not in content, "Orchestrator should not import validate_source_claims"
    
    def test_no_direct_item_analysis_query_in_validation(self):
        """Validation step should delegate to service, not query directly."""
        with open("app/services/pipeline_orchestrator.py", "r") as f:
            tree = ast.parse(f.read())
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_step_validation":
                # Should not have direct DB queries
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Attribute):
                            if child.func.attr == "query":
                                pytest.fail("_step_validation should not have direct DB queries")
    
    def test_normalize_delegates_to_service(self):
        """Normalize step should delegate to NormalizeService."""
        with open("app/services/pipeline_orchestrator.py", "r") as f:
            content = f.read()
        
        assert "NormalizeService" in content, "Orchestrator should import NormalizeService"
        assert "normalize_batch" in content, "Orchestrator should call normalize_batch"
    
    def test_validation_delegates_to_service(self):
        """Validation step should delegate to ValidationService."""
        with open("app/services/pipeline_orchestrator.py", "r") as f:
            content = f.read()
        
        assert "ValidationService" in content, "Orchestrator should import ValidationService"
        assert "validate_batch" in content, "Orchestrator should call validate_batch"
