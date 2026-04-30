import json
import sys
from pathlib import Path

class ProjectManager:
    PROJECTS_FILE = Path(sys.argv[0]).resolve().parent / "data" / "projects.json"

    @classmethod
    def load_projects(cls):
        if cls.PROJECTS_FILE.exists():
            try:
                with open(cls.PROJECTS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading projects: {e}")
        return []

    @classmethod
    def save_projects(cls, projects):
        try:
            with open(cls.PROJECTS_FILE, "w", encoding="utf-8") as f:
                json.dump(projects, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving projects: {e}")

    @classmethod
    def add_project(cls, project_data):
        projects = cls.load_projects()
        # 重複チェック（IDで判定）
        for i, p in enumerate(projects):
            if p.get("project_id") == project_data.get("project_id"):
                projects[i] = project_data
                cls.save_projects(projects)
                return
        projects.append(project_data)
        cls.save_projects(projects)
