# SG-image stock notification

This repo watches the SG-image AF35mm f/2.2 lens Shopify listing and alerts when the `L / With Square Lens Hood` variant (`48131425272033`) is in stock.

## How it works

- GitHub Actions runs `.github/workflows/sg-image-l-mount-stock.yml` every 5 minutes, which is GitHub's fastest cron interval.
- The workflow fetches both the store's Shopify product JSON endpoint and the rendered product page for the target variant.
- It alerts only when both signals agree the `L / With Square Lens Hood` variant is purchasable, which helps avoid false positives when the storefront page and Shopify data disagree.
- When the lens is in stock, the workflow opens or reopens a GitHub issue titled `SG-image AF35mm f/2.2 L-mount is in stock`.
- When it goes out of stock again, the workflow comments on that issue and closes it so the next restock can alert again.

## How you get notified

- GitHub will notify you through its normal channels when the workflow opens or reopens the alert issue.
- For the strongest signal, make sure you are watching the repo or at least subscribed to the created issue, and that your GitHub email or mobile notifications are enabled.
- The workflow assigns the alert issue to the repository owner by default.

## Manual run

You can also trigger the workflow anytime from the Actions tab with `Run workflow`.
