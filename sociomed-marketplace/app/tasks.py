from whatsapp_bot import celery_app, logger
from etl_ingest import run_etl  # or your Excel function
# If you have excel_ingest, import that too

@celery_app.task
def run_pdf_import():
    """Background task for PDF import"""
    try:
        run_etl()  # Your existing function
        logger.info("PDF import completed")
        # Optional: Send WhatsApp to admin
        # send_whatsapp_message("256YOURPHONE", "✅ PDF Import Complete!")
    except Exception as e:
        logger.error(f"PDF import failed: {e}")

@celery_app.task
def run_excel_import():
    """Background task for Excel import"""
    try:
        # Call your excel_ingest function
        logger.info("Excel import completed")
    except Exception as e:
        logger.error(f"Excel import failed: {e}")
