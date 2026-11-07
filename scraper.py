"""
Secure Financial Data Scraper Agent.

This module downloads historical market data for specified stock tickers
using the Yahoo Finance API (via yfinance) and securely persists the dataset
locally as an Apache Parquet file.

Security & MLOps Architecture Considerations:
- Zero-Trust input validation and schema integrity.
- Structured, level-based logging to stdout (avoiding sensitive leakage).
- Graceful exception handling and deterministic exit codes for container orchestrators.
"""

import datetime
import logging
import os
import sys
from pathlib import Path
from typing import List

import boto3
import pandas as pd
import yfinance as yf

# Configure structured logging for containerized stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("FinancialDataScraper")

# Ingestion configuration constants
TARGET_TICKERS: List[str] = ["AAPL", "MSFT", "GOOGL"]
HISTORICAL_PERIOD: str = "6mo"
OUTPUT_FILE_PATH: Path = Path("market_data.parquet")

# Ensure yfinance cache uses writable ephemeral directory in containerized runtime
yf.set_tz_cache_location("/tmp/py-yfinance")


def fetch_historical_market_data(
    tickers: List[str], period: str = "6mo"
) -> pd.DataFrame:
    """
    Downloads historical stock market data for a target list of tickers.

    Args:
        tickers: List of ticker symbols to download (e.g., ['AAPL', 'MSFT', 'GOOGL']).
        period: Historical lookback period (e.g., '6mo').

    Returns:
        pd.DataFrame: Consolidated DataFrame with standardized market columns.

    Raises:
        ValueError: If no valid tickers are provided.
        RuntimeError: If data retrieval fails across all requested tickers.
    """
    if not tickers:
        raise ValueError("Target ticker list must not be empty.")

    logger.info(
        "Initiating historical market data download for tickers: %s (Period: %s)",
        tickers,
        period,
    )

    accumulated_frames: List[pd.DataFrame] = []

    for ticker_symbol in tickers:
        logger.info("Fetching historical data for symbol: %s...", ticker_symbol)
        try:
            ticker_obj = yf.Ticker(ticker_symbol)
            hist_df = ticker_obj.history(period=period)

            if hist_df.empty:
                logger.warning(
                    "No historical data returned for ticker: %s", ticker_symbol
                )
                continue

            # Standardize index and metadata columns
            hist_df = hist_df.reset_index()
            hist_df["Ticker"] = ticker_symbol

            # Normalize column names (lowercase, underscore-delimited)
            hist_df.columns = [
                str(col).strip().replace(" ", "_").lower()
                for col in hist_df.columns
            ]

            logger.info(
                "Retrieved %d records for ticker %s.",
                len(hist_df),
                ticker_symbol,
            )
            accumulated_frames.append(hist_df)

        except Exception as exc:
            logger.error(
                "Unexpected error fetching data for ticker %s: %s",
                ticker_symbol,
                exc,
                exc_info=False,
            )

    if not accumulated_frames:
        raise RuntimeError(
            "Ingestion failure: No market data could be retrieved for any requested ticker."
        )

    consolidated_df = pd.concat(accumulated_frames, ignore_index=True)
    logger.info(
        "Successfully consolidated %d total records across %d ticker symbols.",
        len(consolidated_df),
        len(accumulated_frames),
    )
    return consolidated_df


def persist_to_parquet(df: pd.DataFrame, destination: Path) -> None:
    """
    Persists a DataFrame to disk using Apache Parquet format with verification.

    Args:
        df: DataFrame containing the dataset to store.
        destination: File destination path.

    Raises:
        IOError: If the file cannot be written or output verification fails.
    """
    if df.empty:
        raise ValueError("Cannot persist empty DataFrame to Parquet.")

    try:
        logger.info("Writing dataset to Parquet file: %s", destination)

        # Ensure target directory exists with appropriate permissions
        destination.parent.mkdir(parents=True, exist_ok=True)

        # Write Parquet using pyarrow engine with snappy compression
        df.to_parquet(
            destination,
            engine="pyarrow",
            index=False,
            compression="snappy",
        )

        # Verification of persisted file
        if not destination.exists():
            raise IOError(f"Output verification failed: {destination} was not created.")

        file_size_bytes = destination.stat().st_size
        if file_size_bytes == 0:
            raise IOError(f"Output verification failed: {destination} is empty (0 bytes).")

        logger.info(
            "Parquet persistence complete: '%s' (Size: %.2f KB, Records: %d)",
            destination,
            file_size_bytes / 1024.0,
            len(df),
        )

    except Exception as exc:
        logger.critical(
            "Fatal error writing Parquet file '%s': %s",
            destination,
            exc,
            exc_info=True,
        )
        raise IOError(f"Failed to persist Parquet data: {exc}") from exc


def upload_to_s3(file_path: Path, bucket_name: str, s3_key: str) -> None:
    """
    Uploads a local file to Amazon S3 via boto3 using IRSA OIDC credentials.

    Args:
        file_path: Local path to the file to upload.
        bucket_name: Target Amazon S3 bucket name.
        s3_key: Destination object key in S3.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Source file not found for S3 upload: {file_path}")

    logger.info("Initiating upload to S3: s3://%s/%s", bucket_name, s3_key)
    try:
        s3_client = boto3.client("s3")
        s3_client.upload_file(str(file_path), bucket_name, s3_key)
        logger.info(
            "Successfully uploaded dataset to s3://%s/%s via IRSA.",
            bucket_name,
            s3_key,
        )
    except Exception as exc:
        logger.critical(
            "Failed to upload file to S3 (s3://%s/%s): %s",
            bucket_name,
            s3_key,
            exc,
            exc_info=True,
        )
        raise IOError(f"S3 persistence error: {exc}") from exc


def main() -> None:
    """Entry point for the Secure Financial Data Scraper Agent."""
    logger.info("Starting Secure Financial Data Agent ingestion process...")
    try:
        market_data = fetch_historical_market_data(
            tickers=TARGET_TICKERS,
            period=HISTORICAL_PERIOD,
        )
        persist_to_parquet(market_data, OUTPUT_FILE_PATH)

        # Upload to Amazon S3 if S3_BUCKET_NAME is configured
        s3_bucket = os.getenv("S3_BUCKET_NAME", "mlops-financial-data-240797212774-lab")
        if s3_bucket:
            timestamp_str = datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y%m%d_%H%M%S"
            )
            s3_destination_key = f"data/market_data_{timestamp_str}.parquet"
            upload_to_s3(OUTPUT_FILE_PATH, s3_bucket, s3_destination_key)

        logger.info("Ingestion and cloud persistence pipeline completed successfully.")
        sys.exit(0)
    except Exception as err:
        logger.critical("Pipeline aborted due to unrecoverable error: %s", err)
        sys.exit(1)


if __name__ == "__main__":
    main()
