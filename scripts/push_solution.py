import os
import json
from hashlib import md5
from glob import glob

from dotenv import load_dotenv
import requests  # 2.31.0

from utils import SolutionData, parse_metadata, EXTENSION_TO_LANGUAGE, EXTENSION_TO_CODE, OJ_NAMES

load_dotenv()


def get_github_action_var(
    configs: dict[str, str] = {},
) -> dict[str, str]:
    if len(configs.keys()) > 0:
        return configs
    
    vars = [
        "API_AUTH_URL",
        "API_SOLUTION_URL",
        "API_SYSTEM_USER_ID",
        "API_SYSTEM_USER_PW",
    ]
    for var in vars:
        configs[var] = os.environ.get(var, "")
    return configs


def make_problem_dict(
    configs: dict[str, str] = get_github_action_var(),
    problem_id_dict: dict[str, dict[str, int]] = {},
):
    if len(problem_id_dict.keys()) > 0:
        return problem_id_dict
    
    for oj_name in OJ_NAMES:

        if oj_name not in problem_id_dict:
            problem_id_dict[oj_name] = {}
        
        step = 0
        while True:
            # print(f"{oj_name} {500} {500 * step}")
            params = {
                "oj_name": oj_name,
                "orderby_column": "problem_id",
                "limit": 500,
                "offset": 500 * step
            }

            url = f"{configs['API_SOLUTION_URL']}/problem"
            response = requests.get(url, params=params)
            response.raise_for_status()
            problems = response.json()["data"]
            if len(problems) == 0:
                break

            for problem in problems:
                problem_id_dict[oj_name][problem["oj_problem_number"]] = problem["id"]

            step += 1
    
    return problem_id_dict


def get_access_token(
    configs: dict[str, str] = get_github_action_var(),
    token: dict[str, str] = {},
) -> str:
    if "access_token" in token:
        return token["access_token"]
    
    url = f"{configs['API_AUTH_URL']}/auth/login"
    data = {
        "email": configs["API_SYSTEM_USER_ID"],
        "password": configs["API_SYSTEM_USER_PW"],
    }
    res = requests.post(url, json=data)
    res.raise_for_status()

    token["access_token"] = res.json()["access_token"]
    return token["access_token"]


def source_code_to_hash(code_lines: list[str]) -> str:
    enc = md5()
    enc.update("".join(code_lines).encode())
    return enc.hexdigest()


def get_problem_id(
    oj_name: str, 
    problem_number: str,
    configs: dict[str, str] = get_github_action_var(),
) -> int:
    url = f"{configs['API_SOLUTION_URL']}/problem/problem-id"
    params = {"oj_name": oj_name, "problem_number": problem_number}
    return requests.get(url, params=params).json()["id"]


def precheck_all_comment():
    wrong_files = []

    for oj_name in OJ_NAMES:
        root_path = f"solutions/{oj_name}/**/*.*"
        files = glob(root_path, recursive=True)
        for file in files:
            with open(file, 'r') as f:
                code_lines = f.readlines()
                f.close()
            
            res = parse_metadata(code_lines)
            if len(res.keys()) != 3:
                wrong_files.append(file)
    
    print(*wrong_files, sep='\n')
    if len(wrong_files) > 0:
        raise Exception("형식이 잘못된 솔루션이 있습니다.")


def update_solutions(
    solution_data: SolutionData,
    configs: dict[str, str] = get_github_action_var(),
    access_token: str = get_access_token(),
    # problem_id_info: dict[str, dict[str, int]] = make_problem_dict(),
):
    for oj_name in OJ_NAMES:
        root_path = f"solutions/{oj_name}/**/*.*"
        files = glob(root_path, recursive=True)
        for file in files:
            with open(file, 'r') as f:
                code_lines = f.readlines()
                f.close()

            hash_value = source_code_to_hash(code_lines)
            filename = os.path.basename(file)
            ext = os.path.splitext(file)[-1].lstrip('.')
            language = EXTENSION_TO_LANGUAGE[ext]
            metadata = parse_metadata(code_lines)
            metadata["language"] = language
            pid = file.split("/")[-2]

            if solution_data.check_uploaded_solution(
                oj_name=oj_name,
                pid=pid,
                filename=filename,
                hash_value=hash_value
            ):
                continue

            sequence = solution_data.get_sequence(
                oj_name=oj_name,
                pid=pid,
                filename=filename,
            )

            idx = len(code_lines) - 1
            start_line, end_line = -1, -1
            for idx in range(len(code_lines) - 1, -1, -1):
                if code_lines[idx].strip() != "":
                    if end_line == -1:
                        end_line = idx
                
                if 'Solution Description' in code_lines[idx]:
                    start_line = idx
                    break
            
            solution_description = ""
            if start_line != -1 and end_line != -1:
                solution_description = "".join(code_lines[start_line + 1: end_line])
                code_lines = code_lines[:start_line]
                while code_lines and code_lines[-1].strip() == "":
                    code_lines.pop(-1)
                
                code = "".join(code_lines[:start_line])
            else:
                code = "".join(code_lines)
            
            description = f"```{EXTENSION_TO_CODE[ext]}\n{code}\n```\n\n{solution_description}"
            
            problem_id = get_problem_id(oj_name=oj_name, problem_number=pid)

            url = f"{configs['API_SOLUTION_URL']}/problem/{problem_id}/solution"

            if sequence == -1:
                data = {
                    "problem_id": problem_id,
                    "language": metadata["language"],
                    "author": metadata["Authored by"],
                    "description": description,
                }
                response = requests.post(url, headers={"Authorization": f"Bearer {access_token}"}, json=data)
            else:
                data = {
                    "problem_id": problem_id,
                    "language": metadata["language"],
                    "sequence": sequence,
                    "author": metadata["Authored by"],
                    "description": description,
                }
                response = requests.put(url, headers={"Authorization": f"Bearer {access_token}"}, json=data)

            response.raise_for_status()
            print(response.request.method, response.url, response.status_code)
            seq = response.json()["id"]
            solution_data.update_data(
                oj_name=oj_name,
                pid=pid,
                filename=filename,
                hash_value=hash_value,
                sequence=seq,
            )


if __name__ == "__main__":
    try:
        precheck_all_comment()
        solution_data = SolutionData()
        update_solutions(solution_data=solution_data)
    except KeyboardInterrupt as e:
        solution_data.save()
        print("Saved")
    finally:
        solution_data.save()