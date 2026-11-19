# NormsAI · Quota Library

[中文](README.md) · **English**

NormsAI is the Cost Center's quota library. Browse construction quotas by volume and chapter, inspect labour, material and equipment quantities, and use price packs to build unit rates and export Excel files. [Live site](https://checcost.com/norms/norms_browser.html)

## Run locally

Install Git and Python 3.12 or 3.13. If you already have the repository, open its folder in a terminal and run the last command.

```bash
git clone https://github.com/pengkang135/NormsAI.git
cd NormsAI
python start.py
```

Open [http://localhost:18080/norms_browser.html](http://localhost:18080/norms_browser.html). Press `Ctrl+C` in the server terminal to stop it.

- If port `18080` is in use, run `python start.py --port 18180 --no-open`, then open [http://localhost:18180/norms_browser.html](http://localhost:18180/norms_browser.html).
- To test Excel export, run `python -m pip install openpyxl` in your Python environment and restart the server.
- The browser page is `output/norms_browser.html`. The API starts from `start.py` and reads SQLite files in `db/`. Ask the Cost Center for the appropriate development sample if a volume or price pack is missing. [Database index](db/INDEX.md)

## Submit changes

1. **Get collaborator access.** Send the repository owner your GitHub username and what you want to work on. Accept the invitation with that same account.
2. **Create a branch.** Start from the version agreed with the owner. The example uses `master`, the repository's default branch.
3. **Test locally and push.** Start the site using the steps above to check your changes. Stage the files relevant to your change and use approved sample data.

```bash
git switch master
git pull --ff-only
git switch -c docs/norms-guide
# After editing and testing, add the files you changed
git add README.md
git commit -m "docs: update NormsAI guide"
git push -u origin docs/norms-guide
```

4. **Open a pull request (PR).** Open the [repository](https://github.com/pengkang135/NormsAI) on GitHub and select **Compare & pull request**. Check the target branch and explain what changed and how you tested it. Add screenshots for visual changes. If the owner asks for revisions, push to the same branch to update the PR. The repository owner merges the PR and handles the live release.

In GitHub Desktop, use **Current Branch → New Branch**. After editing and testing, use **Commit to… → Publish branch → Preview Pull Request**, then finish opening the PR on GitHub.
