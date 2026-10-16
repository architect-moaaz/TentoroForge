"""A sub-department used to vanish from the organisation chart (only root
departments were returned, children were never nested); its teams and people
went with it. The chart now nests a department under its parent, and a
department whose parent is unknown stands as a root rather than disappearing."""
import pytest


@pytest.mark.asyncio
async def test_a_sub_department_hangs_under_its_parent_with_its_teams_and_people(auth_client, org_id):
    eng = (await auth_client.post(f"/api/orgs/{org_id}/departments", json={"name": "Engineering"})).json()
    qa = (await auth_client.post(f"/api/orgs/{org_id}/departments", json={"name": "QA", "parent_id": eng["id"]})).json()
    forge = (await auth_client.post(f"/api/orgs/{org_id}/teams", json={"name": "Forge", "department_id": eng["id"]})).json()
    bench = (await auth_client.post(f"/api/orgs/{org_id}/teams", json={"name": "Bench", "department_id": qa["id"]})).json()
    await auth_client.post(f"/api/orgs/{org_id}/people", json={
        "email": "mo@example.com", "first_name": "Moaaz", "last_name": "Shareef", "title": "Director", "team_id": forge["id"]})
    await auth_client.post(f"/api/orgs/{org_id}/people", json={
        "email": "ann@example.com", "first_name": "Ann", "last_name": "Lee", "department_id": qa["id"]})
    await auth_client.post(f"/api/orgs/{org_id}/people", json={
        "email": "zed@example.com", "first_name": "Zed", "last_name": "Null"})

    r = await auth_client.get(f"/api/orgs/{org_id}/org-chart")
    assert r.status_code == 200
    chart = r.json()
    assert [d["name"] for d in chart["departments"]] == ["Engineering"]
    root = chart["departments"][0]
    assert [t["name"] for t in root["teams"]] == ["Forge"]
    assert [p["first_name"] for p in root["teams"][0]["people"]] == ["Moaaz"]
    assert [c["name"] for c in root["children"]] == ["QA"]
    child = root["children"][0]
    assert [t["name"] for t in child["teams"]] == ["Bench"] and bench["id"] == child["teams"][0]["id"]
    assert [p["first_name"] for p in child["people"]] == ["Ann"]
    assert [p["first_name"] for p in chart["unassigned_people"]] == ["Zed"]
