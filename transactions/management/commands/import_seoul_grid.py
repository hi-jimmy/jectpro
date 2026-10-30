from pathlib import Path

import shapefile
from django.core.management.base import BaseCommand, CommandError

from transactions.models import SeoulGridCell


class Command(BaseCommand):
    help = "Import Seoul's 250m grid SHP (EPSG:5179) into the database."

    def add_arguments(self, parser):
        parser.add_argument("shapefile", help="Path to .shp file (sidecar .shx/.dbf files must be present)")
        parser.add_argument("--cell-field", help="Attribute containing the grid cell ID; auto-detected when omitted")

    def handle(self, *args, **options):
        shp_path = Path(options["shapefile"])
        if not shp_path.is_file() or shp_path.suffix.lower() != ".shp":
            raise CommandError("Provide the extracted .shp file; its .shx and .dbf sidecars must be alongside it.")
        projection_path = shp_path.with_suffix(".prj")
        if not projection_path.is_file():
            raise CommandError("The .prj projection sidecar is required to confirm EPSG:5179.")
        projection = projection_path.read_text(encoding="utf-8", errors="ignore").upper()
        if "5179" not in projection and "KOREAN 2000 / CENTRAL BELT 2010" not in projection:
            raise CommandError("This importer expects the official grid shapefile in EPSG:5179.")
        try:
            reader = shapefile.Reader(str(shp_path), encoding="utf-8")
        except (OSError, shapefile.ShapefileException) as exc:
            raise CommandError(f"Could not read shapefile: {exc}") from exc

        field_names = [field[0] for field in reader.fields[1:]]
        normalized_fields = {name.upper(): name for name in field_names}
        cell_field = options["cell_field"] or next((normalized_fields[name] for name in ("CELL_ID", "GRID_ID", "격자ID", "ID") if name in normalized_fields), None)
        admin_field = next((normalized_fields[name] for name in ("H_DNG_CD", "ADSTRD_CD", "ADM_CD", "행정동코드") if name in normalized_fields), None)
        if not cell_field:
            raise CommandError(f"Could not identify the grid ID field. Available fields: {', '.join(field_names)}. Use --cell-field.")

        count = 0
        for shape_record in reader.iterShapeRecords():
            properties = dict(zip(field_names, list(shape_record.record)))
            cell_id = str(properties.get(cell_field, "")).strip()
            if not cell_id:
                continue
            geometry = shape_record.shape.__geo_interface__
            administrative_code = str(properties.get(admin_field, "")) if admin_field else ""
            SeoulGridCell.objects.update_or_create(
                cell_id=cell_id,
                defaults={"administrative_code": administrative_code, "geometry": geometry, "properties": properties},
            )
            count += 1
            if count % 1000 == 0:
                self.stdout.write(f"Imported {count} grid cells")
        self.stdout.write(self.style.SUCCESS(f"Imported {count} grid cells from {shp_path.name}; source coordinates are retained as EPSG:5179."))