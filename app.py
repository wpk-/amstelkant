"""Fetches tiles from a Web Map Tile Service (WMTS).

The file `doc/07-057r7_Web_Map_Tile_Service_Standard.pdf` provides
documentation for the WMTS standard and calculations.

Example run (see also bottom of this script):
>>> tm = TileMatrix(wmts_url, ..., zoom, ...)
>>> lower = Rijksdriehoek(121364, 487333)
>>> upper = Rijksdriehoek(121464, 487433)
>>> area = BoundingBox(lower, upper)
>>> for tile in tm.fetch(area):
>>>     print(tile)
>>>     # Do your thing. Copy the image if you need it.
>>> # The images, downloaded to a temp folder, will be deleted after iteration.
"""
import shutil
import tempfile
from math import floor
from os.path import join as joinpath
from typing import Iterator, NamedTuple, Union

from owslib.wmts import WebMapTileService


class Rijksdriehoek(NamedTuple):
    """A class for coordinates in the Rijksdriehoek coordinate system.
    """
    x: float
    y: float

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(x={self.x:.8g}, y={self.y:.8g})'


class BoundingBox(NamedTuple):
    """Defines a region contained between a lower and upper coordinate.
    """
    lower: Rijksdriehoek
    upper: Rijksdriehoek


class TileIndex(NamedTuple):
    """A class for coordinates in the tile matrix coordinate system.
    """
    row: int    # note: row is vertical.
    col: int


class Tile(NamedTuple):
    # Asserts that you know the `TileMatrix` it belongs to.
    index: TileIndex
    filename: str
    bbox: BoundingBox


class TileMatrix:
    """
    See: 07-057r7_Web_Map_Tile_Service_Standard.pdf, pp. 8-9 + annex H.
    """
    def __init__(self, url: str, layer: str, tile_system: str,
                 tile_level: Union[str, int], format: str) -> None:
        """Creates a tile matrix (WMTS layer at fixed zoom level).

        Args:
            url: The URL to the Web Map Tile Service (WMTS).
            layer: The WMTS layer name.
            tile_system: Name of the tile system (should use the
                Rijksdriehoek coordinate system, or at least use 1-metre
                units).
            tile_level: The zoom level.
            format: The image format for tiles. Usually either
                `image/png` or `image/jpeg`.
        """
        self.wmts = WebMapTileService(url)
        self.layer = layer
        self.tile_system = tile_system
        self.tile_level = str(tile_level)
        self.format = format

        assert layer in self.wmts.contents, \
            'Layer not found.'
        assert tile_system in self.wmts.tilematrixsets, \
            'Tile matrix set not found.'
        assert tile_system in self.wmts.contents[layer].tilematrixsetlinks, \
            'Tile system not found.'
        assert format in self.wmts.contents[layer].formats, \
            'Unsupported format.'

        # See: pdf, pp. 8-9
        # (Top left corner is min x and max y.)
        # Note: Rijksdriehoek metric is in metres. This is relevant
        #   because the scaling parameter has been omitted for this
        #   reason.
        self.matrix = (self.wmts
                       .tilematrixsets[tile_system]
                       .tilematrix[str(tile_level)])
        self.pixel_span = self.matrix.scaledenominator * 0.28 * 1e-3
        self.span_x = self.matrix.tilewidth * self.pixel_span
        self.span_y = self.matrix.tileheight * self.pixel_span

    def bbox_tiles(self, bbox: BoundingBox) -> Iterator[TileIndex]:
        """Iterates over all tiles that intersect the bounding box.
        Yields `TileIndex` instances.
        """
        def _rd_to_tile(xy: Rijksdriehoek) -> TileIndex:
            """Maps one RD coordinate to an unrounded (float) tile index.
            """
            # See: pdf, annex H.1.
            return TileIndex((top_left_corner[1] - xy.y) / tile_span_y,
                             (xy.x - top_left_corner[0]) / tile_span_x)

        matrix_height = self.matrix.matrixheight
        matrix_width = self.matrix.matrixwidth
        tile_span_x = self.span_x
        tile_span_y = self.span_y
        top_left_corner = self.matrix.topleftcorner

        # See: pdf, annex H.1.
        row_max, col_min = _rd_to_tile(bbox.lower)
        row_min, col_max = _rd_to_tile(bbox.upper)

        eps = 1e-6
        row_min = max(floor(row_min + eps), 0)
        col_min = max(floor(col_min + eps), 0)
        row_max = min(floor(row_max - eps), matrix_height - 1)
        col_max = min(floor(col_max - eps), matrix_width - 1)

        return (TileIndex(row, col)
                for row in range(row_min, row_max + 1)
                for col in range(col_min, col_max + 1))

    def fetch(self, bbox: BoundingBox) -> Iterator[Tile]:
        """Fetches all tiles in the bounding box.
        Iterates over the tiles (with pointers to the downloaded images).
        Deletes all images after iteration.
        """
        dir_path = tempfile.mkdtemp()
        ext = self.format.split('/')[-1]
        for index in self.bbox_tiles(bbox):
            filename = joinpath(dir_path, f'{index.row}_{index.col}.{ext}')
            yield self.fetch_tile(index, filename)
        # Clean up.
        shutil.rmtree(dir_path)

    def fetch_tile(self, index: TileIndex, filename: str) -> Tile:
        """Fetches a tile by its tile index.
        Returns the index, image and bounding box.
        """
        res = self.wmts.gettile(layer=self.layer,
                                tilematrixset=self.tile_system,
                                tilematrix=self.tile_level,
                                row=index.row,
                                column=index.col,
                                format=self.format)
        with open(filename, 'wb') as f:
            f.write(res.read())
        return Tile(index, filename, self.tile_bbox(index))

    def tile_bbox(self, tile: TileIndex) -> BoundingBox:
        """Maps a tile index to its Rijksdriehoek bounding box.
        """
        x_min = tile.col * self.span_x + self.matrix.topleftcorner[0]
        y_max = self.matrix.topleftcorner[1] - tile.row * self.span_y

        # See: pdf, annex H.2.
        lower = Rijksdriehoek(x_min, y_max - self.span_y)
        upper = Rijksdriehoek(x_min + self.span_x, y_max)

        return BoundingBox(lower, upper)


def print_wmts_info(wmts: WebMapTileService):
    """Getting to know OWSLib.
    """
    print('Identification:')
    print(f'  - type: {wmts.identification.type}')
    print(f'  - version: {wmts.identification.version}')
    print(f'  - title: {wmts.identification.title}')
    print(f'  - abstract: {wmts.identification.abstract}')
    print('Provider:')
    print(f'  - name: {wmts.provider.name}')
    print(f'  - URL: {wmts.provider.url}')
    print('Contents:')
    # (`contents` is a dict.)
    for x in wmts.contents:
        print(f'  - {x}')
    print('Tile matrix sets:')
    # (`tilematrixsets` is a dict.)
    for x in wmts.tilematrixsets:
        print(f'  - {x}')


if __name__ == '__main__':
    # The map of Amsterdam WMTS defines tiles for zoom levels 5-16.
    # Get the 'luchtfoto' (aerial) layer at fixed zoom level.
    lufo_url = ('https://map.data.amsterdam.nl/service?'
                'REQUEST=GetCapabilities&SERVICE=WMTS')
    tm = TileMatrix(lufo_url, 'lufo_rd', 'nl_grid', 12, 'image/jpeg')

    # If you're interested:
    print_wmts_info(tm.wmts)

    # Then grab a set of tiles (images) from it.
    # We query some area around Dam square.
    # At zoom level 12 it should result in exactly six tiles (3 wide, 2 tall).
    # At zoom level 13 it should be twelve tiles (4 wide, 3 tall).
    bbox = BoundingBox(lower=Rijksdriehoek(121198, 487266),
                       upper=Rijksdriehoek(121498, 487416))

    # Note that tiles are always 256 x 256 pixels.
    for tile in tm.fetch(bbox):
        print(tile)
        # Also note that all downloaded tiles will be deleted at the end
        # of the iteration. Therefore, copy the files if you need them.
        shutil.copy(tile.filename, 'C:/Users/Paul/Desktop/amstelkant/tiles/')
