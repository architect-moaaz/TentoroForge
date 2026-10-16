"""A person had one team column, so Moaaz could not be in Forge and Genesys at
once. Membership rows now hold every team a person is in; the home team stays
on the person for every older reader; the chart stands them under each team;
and `manager_id` is how who reports to whom is said."""
import pytest


async def _setup(auth_client, org_id):
    eng = (await auth_client.post(f"/api/orgs/{org_id}/departments", json={"name": "Engineering"})).json()
    forge = (await auth_client.post(f"/api/orgs/{org_id}/teams", json={"name": "Forge", "department_id": eng["id"]})).json()
    genesys = (await auth_client.post(f"/api/orgs/{org_id}/teams", json={"name": "Genesys", "department_id": eng["id"]})).json()
    return eng, forge, genesys


@pytest.mark.asyncio
async def test_team_ids_on_the_person_put_them_in_every_team_named(auth_client, org_id):
    eng, forge, genesys = await _setup(auth_client, org_id)
    r = await auth_client.post(f"/api/orgs/{org_id}/people", json={
        "email": "mo@example.com", "first_name": "Moaaz", "last_name": "Shareef",
        "title": "Director of Technology", "team_ids": [forge["id"], genesys["id"]]})
    assert r.status_code == 201, r.text
    mo = r.json()
    assert mo["team_ids"] == [forge["id"], genesys["id"]] and mo["team_id"] == forge["id"]

    # Both teams list them; the team filter on people sees memberships too.
    for team in (forge, genesys):
        names = [p["first_name"] for p in (await auth_client.get(f"/api/orgs/{org_id}/teams/{team['id']}/members")).json()]
        assert names == ["Moaaz"], team["name"]
    assert [p["id"] for p in (await auth_client.get(f"/api/orgs/{org_id}/people", params={"team_id": genesys["id"]})).json()] == [mo["id"]]

    # The chart stands them under each team.
    chart = (await auth_client.get(f"/api/orgs/{org_id}/org-chart")).json()
    teams = {t["name"]: [p["first_name"] for p in t["people"]] for t in chart["departments"][0]["teams"]}
    assert teams == {"Forge": ["Moaaz"], "Genesys": ["Moaaz"]}
    assert chart["unassigned_people"] == []


@pytest.mark.asyncio
async def test_a_team_takes_a_person_in_and_lets_them_go_without_touching_their_other_teams(auth_client, org_id):
    eng, forge, genesys = await _setup(auth_client, org_id)
    ann = (await auth_client.post(f"/api/orgs/{org_id}/people", json={
        "email": "ann@example.com", "first_name": "Ann", "last_name": "Lee", "team_id": forge["id"]})).json()
    assert ann["team_ids"] == [forge["id"]]

    r = await auth_client.post(f"/api/orgs/{org_id}/teams/{genesys['id']}/members", json={"person_id": ann["id"]})
    assert r.status_code == 201 and sorted(r.json()["team_ids"]) == sorted([forge["id"], genesys["id"]])
    assert r.json()["team_id"] == forge["id"]  # the home team is unchanged

    # Leaving the home team makes the other team home.
    assert (await auth_client.delete(f"/api/orgs/{org_id}/teams/{forge['id']}/members/{ann['id']}")).status_code == 204
    me = next(p for p in (await auth_client.get(f"/api/orgs/{org_id}/people")).json() if p["id"] == ann["id"])
    assert me["team_ids"] == [genesys["id"]] and me["team_id"] == genesys["id"]

    # Setting team_ids on an edit replaces the set; a team of another organisation is refused.
    r = await auth_client.put(f"/api/orgs/{org_id}/people/{ann['id']}", json={"team_ids": [forge["id"]]})
    assert r.status_code == 200 and r.json()["team_ids"] == [forge["id"]] and r.json()["team_id"] == forge["id"]
    r = await auth_client.put(f"/api/orgs/{org_id}/people/{ann['id']}", json={"team_ids": ["00000000-0000-0000-0000-000000000001"]})
    assert r.status_code == 404
    r = await auth_client.put(f"/api/orgs/{org_id}/people/{ann['id']}", json={"team_ids": []})
    assert r.status_code == 200 and r.json()["team_ids"] == [] and r.json()["team_id"] is None


@pytest.mark.asyncio
async def test_who_reports_to_whom_is_the_manager_on_the_person(auth_client, org_id):
    eng, forge, genesys = await _setup(auth_client, org_id)
    mo = (await auth_client.post(f"/api/orgs/{org_id}/people", json={
        "email": "mo@example.com", "first_name": "Moaaz", "last_name": "Shareef", "team_id": forge["id"]})).json()
    r = await auth_client.post(f"/api/orgs/{org_id}/people", json={
        "email": "ann@example.com", "first_name": "Ann", "last_name": "Lee", "team_id": genesys["id"], "manager_id": mo["id"]})
    assert r.status_code == 201 and r.json()["manager_id"] == mo["id"]
    chart = (await auth_client.get(f"/api/orgs/{org_id}/org-chart")).json()
    people = {p["first_name"]: p for t in chart["departments"][0]["teams"] for p in t["people"]}
    assert people["Ann"]["manager_id"] == mo["id"] and people["Moaaz"]["manager_id"] is None
