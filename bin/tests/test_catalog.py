import sys
from pathlib import Path
import unittest
from urllib.parse import unquote

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build_site import make_catalog


class CatalogTests(unittest.TestCase):
    def test_every_numbered_audio_file_maps_in_script_order(self):
        catalog,media=make_catalog()
        self.assertEqual(len(catalog['sets']),6)
        for item in catalog['sets']:
            indices=[clip['index'] for step in item['steps'] for clip in step['clips']]
            self.assertEqual(indices,list(range(1,item['answerCount']+1)))
            self.assertEqual(len(indices),len(set(indices)))
            for step in item['steps']:
                self.assertTrue(step['prompt'])
                for clip in step['clips']:
                    self.assertTrue(media[unquote(clip['url'].split('?')[0])].is_file())
        first=next(s for s in catalog['sets'] if s['edition']=='edited' and s['vignette']==1)
        self.assertEqual(len(first['steps']),37)
        self.assertEqual(next(s['answerIndices'] for s in first['steps'] if 11 in s['answerIndices']),[11,12])


if __name__=='__main__':unittest.main()
