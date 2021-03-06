#!/usr/bin/env python
# File created on 23 Nov 2011
from __future__ import division

__author__ = "Greg Caporaso"
__copyright__ = "Copyright 2011-2013, The PICRUSt Project"
__credits__ = ["Greg Caporaso","Morgan Langille"]
__license__ = "GPL"
__version__ = "0.9.2-dev"
__maintainer__ = "Greg Caporaso"
__email__ = "gregcaporaso@gmail.com"
__status__ = "Development"

from os.path import abspath, dirname, isdir
from os import mkdir,makedirs
from cogent.core.tree import PhyloNode, TreeError
from numpy import array,asarray
from biom.table import SparseOTUTable, DenseOTUTable, SparsePathwayTable, \
  DensePathwayTable, SparseFunctionTable, DenseFunctionTable, \
  SparseOrthologTable, DenseOrthologTable, SparseGeneTable, \
  DenseGeneTable, SparseMetaboliteTable, DenseMetaboliteTable,\
  SparseTaxonTable, DenseTaxonTable, table_factory
from biom.parse import parse_biom_table,parse_biom_table_str, convert_biom_to_table, \
  convert_table_to_biom
from subprocess import Popen, PIPE, STDOUT
import StringIO

def convert_precalc_to_biom(precalc_in, ids_to_load=None,transpose=True,md_prefix='metadata_'):
    """Loads PICRUSTs tab-delimited version of the precalc file and outputs a BIOM object"""
    
    #if given a string convert to a filehandle
    if type(precalc_in) ==str or type(precalc_in) == unicode:
        fh = StringIO.StringIO(precalc_in)
    else:
        fh=precalc_in

    #first line has to be header
    header_ids=fh.readline().strip().split('\t')
    
    col_meta_locs={}
    for idx,col_id in enumerate(header_ids):
        if col_id.startswith(md_prefix):
            col_meta_locs[col_id[len(md_prefix):]]=idx
    
    end_of_data=len(header_ids)-len(col_meta_locs)
    trait_ids = header_ids[1:end_of_data]
   
    col_meta=[]
    row_meta=[{} for i in trait_ids]

    if ids_to_load:
        ids_to_load=set(ids_to_load)
        load_all_ids=False
    else:
        load_all_ids=True

    matching=[]
    otu_ids=[]
    for line in fh:
        fields = line.strip().split('\t')
        row_id=fields[0]
        if(row_id.startswith(md_prefix)):
            #handle metadata
            
            #determine type of metadata (this may not be perfect)
            metadata_type=determine_metadata_type(line)
            for idx,trait_name in enumerate(trait_ids):
                row_meta[idx][row_id[len(md_prefix):]]=parse_metadata_field(fields[idx+1],metadata_type)

        elif load_all_ids or (row_id in set(ids_to_load)):
            otu_ids.append(row_id)
            matching.append(map(float,fields[1:end_of_data]))

            #add metadata
            col_meta_dict={}
            for meta_name in col_meta_locs:
                col_meta_dict[meta_name]=fields[col_meta_locs[meta_name]]
            col_meta.append(col_meta_dict)

            if not load_all_ids:
                ids_to_load.remove(row_id)

    if not otu_ids:
        raise ValueError,"No OTUs match identifiers in precalculated file. PICRUSt requires an OTU table reference/closed picked against GreenGenes.\nExample of the first 5 OTU ids from your table: {0}".format(', '.join(list(ids_to_load)[:5]))

    if ids_to_load:
       raise ValueError,"One or more OTU ids were not found in the precalculated file!\nAre you using the correct --gg_version?\nExample of (the {0}) unknown OTU ids: {1}".format(len(ids_to_load),', '.join(list(ids_to_load)[:5]))
        
    #note that we transpose the data before making biom obj
    if transpose:
        return table_factory(asarray(matching).T,otu_ids,trait_ids,col_meta,row_meta,constructor=DenseGeneTable)
    else:
        return table_factory(asarray(matching),trait_ids,otu_ids,row_meta,col_meta,constructor=DenseGeneTable)


def convert_biom_to_precalc(biom_in):
    """Converts a biom file into a PICRUSt precalculated tab-delimited file """
    if type(biom_in) == str or type(biom_in) == unicode:
        biom_table=parse_biom_table_str(biom_in)
    else:
        biom_table=parse_biom_table(biom_in)

    col_ids=biom_table.ObservationIds
    row_ids=biom_table.SampleIds

    lines=[]
    header = ['#OTU_IDs']+list(col_ids) 

    col_metadata_names=[]
    #peak at metadata for Samples (e.g. NSTI) so we can set the header
    if biom_table.SampleMetadata:
        col_metadata_names=biom_table.SampleMetadata[0].keys()

    #add the metadata names to the header
    for col_metadata_name in col_metadata_names:
        header.append('metadata_'+col_metadata_name)

    lines.append(map(str,header))

    row_metadata_names=[]
    #peak at metadata for observations (e.g. KEGG_Pathways)
    if biom_table.ObservationMetadata:
        row_metadata_names=biom_table.ObservationMetadata[0].keys()
    
    for metadata_name in row_metadata_names:
        metadata_line=['metadata_'+metadata_name]
        
    #do the observation metadata now             
        for col_id in col_ids:
            metadata = biom_table.ObservationMetadata[biom_table.getObservationIndex(col_id)]
            metadata_line.append(biom_meta_to_string(metadata[metadata_name]))
        lines.append(map(str,metadata_line))
    
    #transpose the actual count data
    transposed_table=biom_table._data.T
    for idx,count in enumerate(transposed_table):
        line=[row_ids[idx]]+map(str,count)
        
        #add the metadata values to the end of the row now
        for meta_name in col_metadata_names:
            line.append(biom_table.SampleMetadata[idx][meta_name])
        lines.append(line)

    return "\n".join("\t".join(map(str,x)) for x in lines)
     

def determine_metadata_type(line):
    if ';' in line:
        if '|' in line:
            return 'list_of_lists'
        else:
            return 'list'
    else:
        return 'string'

def parse_metadata_field(metadata_str,metadata_format='string'):
    if metadata_format == 'string':
        return metadata_str
    elif metadata_format == 'list':
        return [e.strip() for e in metadata_str.split(';')]
    elif metadata_format == 'list_of_lists':
        return [[e.strip() for e in y.split(';')] for y in metadata_str.split('|')]

def biom_meta_to_string(metadata):
    """ Determine which format the metadata is and then convert to a string"""

    #Note that since ';' and '|' are used as seperators we must replace them if they exist
    if type(metadata) ==str or type(metadata)==unicode:
        return metadata.replace(';',':')
    elif type(metadata) == list:
        if type(metadata[0]) == list:
            return "|".join(";".join([y.replace(';',':').replace('|',':') for y in x]) for x in metadata)
        else:
            return ";".join(x.replace(';',':') for x in metadata)


def system_call(cmd, shell=True):
    """Call cmd and return (stdout, stderr, return_value).

    cmd can be either a string containing the command to be run, or a sequence
    of strings that are the tokens of the command.

    Please see Python's subprocess.Popen for a description of the shell
    parameter and how cmd is interpreted differently based on its value.
    
    This code was copied from QIIME's qiime_system_call() (util.py) function on June 3rd, 2013.
    """
    proc = Popen(cmd, shell=shell, universal_newlines=True, stdout=PIPE,
                 stderr=PIPE)
    # communicate pulls all stdout/stderr from the PIPEs to 
    # avoid blocking -- don't remove this line!
    stdout, stderr = proc.communicate()
    return_value = proc.returncode
    return stdout, stderr, return_value

def file_contains_nulls(file):
    """Checks given file for null characters. These are sometimes created on SGE clusters when system IO is overloaded."""

    return '\x00' in open(file,'rb').read()
          

def parse_table_to_biom(table_lines, table_format="tab-delimited",\
    biom_format = 'otu table'): 
    """Read the lines of an open trait table file, and output a .biom table object 
     
    The trait table must be either a biom file, or a picrust tab-delimited file 
    table_format -- must be either 'tab-delimited' or 'biom' 
     
    """ 
    if table_format == "biom": 
        return parse_biom_table(table_lines) 
    elif table_format == "tab-delimited": 
         
        idx = 0 # a sparse BIOM table 
        BIOM_TYPES = {'otu table':[SparseOTUTable, DenseOTUTable], 
              'pathway table':[SparsePathwayTable, DensePathwayTable], 
              'function table':[SparseFunctionTable, DenseFunctionTable], 
              'ortholog table':[SparseOrthologTable, DenseOrthologTable], 
              'gene table':[SparseGeneTable, DenseGeneTable], 
              'metabolite table':[SparseMetaboliteTable, DenseMetaboliteTable], 
              'taxon table':[SparseTaxonTable, DenseTaxonTable]} 
 
 
        constructor = BIOM_TYPES[biom_format][idx] 
        sample_mapping = None 
        obs_mapping = None 
        process_func = None
        try: 
            converted_table = (convert_table_to_biom(table_lines,\
              sample_mapping,obs_mapping,process_func, constructor)) 
            biom_table = parse_biom_table(converted_table) 
            #print biom_table 
        except ValueError: 
            raise ValueError("Input does not look like a classic table.") 
     
        #headers, fields = parse_trait_table(table_lines) 
        #now convert to biom 
        return biom_table  


#def map_metadata_by_key(biom_table,metadata,keys_are="sample_ids"):
#    """Map a dict of metadata to a biom table
#    biom_table -- a BIOM format table
#    metadata -- a dictionary of metadata values, 
#    keyed by either sample or observation id.
#    keys_are -- choose 'sample_ids' or 'observation_ids'
#
#    NOTE: if your metadata dict is already keyed by metadata label,
#    and is a list, use the biom objects built in functions instead
#    of this.
#    
#    """
#    metadata_keys = metadata_dict.keys()
#    result_list = []*len(metadata_keys)
#    for k in metadata_keys:
#        if keys_are == 'sample_ids':
#            curr_idx = biom_table.getSampleIndex(k) 
#            result_list[k] = metadata
#            biom_table.getSampleIndex(k)
#        elif keys_are == 'observation_ids':
#            result_list[k] = metadata
#            biom_table.getObservationIndex(k)
#        else:
#            raise ValueError('keys_are must be "sample_ids", or "observation_ids", not "%s"' %(keys_are))
#


def get_picrust_project_dir():
    """ Returns the top-level PICRUST directory
    """
    # Get the full path of util.py
    current_file_path = abspath(__file__)
    # Get the directory containing util.py
    current_dir_path = dirname(current_file_path)
    # Return the directory containing the directory containing util.py
    return dirname(current_dir_path)


def transpose_trait_table_fields(data_fields,header,id_row_idx=0,\
    input_header_delimiter="\t",output_delimiter="\t"):
    """Transpose the fields of a trait table, returning new data_fields,header
    
    data_fields:  list of lists for data fields 
    header:  a string describing the header_line
    id_row_idx:  index of row labels.  Almost always 0 but included for 
    but included for completeness

    input_header_delimiter: delimiter for fields in the header string
    output_delimiter: use this delimiter to join header fields

    NOTE:  typically the header and data fields are generated
    by parse_trait_table in picrust.parse
    """
    
    header_fields = header.split(input_header_delimiter)
    
    #ensure no trailing newlines
    old_header_fields = [h.strip() for h in header_fields]
    new_header_fields = [old_header_fields[0]]+\
      [df[id_row_idx].strip() for df in data_fields]

    non_label_data_fields = []
    for row in data_fields:
        non_label_fields =\
          [e for i,e in enumerate(row) if i != id_row_idx]
        non_label_data_fields.append(non_label_fields)


    data_array = array(non_label_data_fields)
    new_data_array = data_array.T
    
    new_rows = []
    for i,row in enumerate(new_data_array):
        label = old_header_fields[i+1] 
        #this is i+1 not i because i is the blank/meaningless
        #upper left corner entry.
        new_row= [label]+list(row)
        new_rows.append(new_row)
    new_header = output_delimiter.join(new_header_fields)
    
    return new_header+"\n",new_rows

def make_output_dir_for_file(filepath):
    """Create sub-directories for a new file if they don't already exist
    """

    dirpath=dirname(filepath)
    if not isdir(dirpath) and not dirpath=='':
        makedirs(dirpath)

def format_biom_table(biom_table):
    """ Given a biom-format Table object, returns that Table as a BIOM string"""
    generated_by_str = "PICRUSt " + __version__
    return biom_table.getBiomFormatJsonString(generated_by_str)

def make_output_dir(dirpath, strict=False):
    """Make an output directory if it doesn't exist
    
    Returns the path to the directory
    dirpath -- a string describing the path to the directory
    strict -- if True, raise an exception if dir already 
    exists
    """
    dirpath = abspath(dirpath)
    
    #Check if directory already exists
    if isdir(dirpath):
        if strict==True:
            err_str = "Directory '%s' already exists" % dirpath
            raise IOError(err_str)
        
        return dirpath
    try:
        makedirs(dirpath)
    except IOError,e:
        err_str = "Could not create directory '%s'. Are permissions set correctly? Got error: '%s'" %e 
        raise IOError(err_str)

    return dirpath




class PicrustNode(PhyloNode):
    def multifurcating(self, num, eps=None, constructor=None):
        """Return a new tree with every node having num or few children

        num : the number of children a node can have max
        eps : default branch length to set if self or constructor is of
            PhyloNode type
        constructor : a TreeNode or subclass constructor. If None, uses self
        """
        if num < 2: 
            raise TreeError, "Minimum number of children must be >= 2"

        if eps is None:
            eps = 0.0

        if constructor is None:
            constructor = self.__class__

        if hasattr(constructor, 'Length'):
            set_branchlength = True 
        else:
            set_branchlength = False

        new_tree = self.copy()

        for n in new_tree.preorder(include_self=True):
            while len(n.Children) > num: 
                new_node = constructor(Children=n.Children[-num:])

                if set_branchlength:
                    new_node.Length = eps

                n.append(new_node)

        return new_tree

    def bifurcating(self, eps=None, constructor=None):
        """Wrap multifurcating with a num of 2"""
        return self.multifurcating(2, eps, constructor)

    def nameUnnamedNodes(self):
        """sets the Data property of unnamed nodes to an arbitrary value
        
        Internal nodes are often unnamed and so this function assigns a
        value for referencing.
        Note*: This method is faster then pycogent nameUnnamedNodes() 
        because it uses a dict instead of an array. Also, we traverse 
        only over internal nodes (and not including tips)
        """

        #make a list of the names that are already in the tree
        names_in_use = {}
        for node in self.iterNontips(include_self=True):
            if node.Name:
                names_in_use[node.Name]=1
    
        #assign unique names to the Data property of nodes where Data = None
        name_index = 1
        for node in self.iterNontips(include_self=True):
            #if (not node.Name) or re.match('edge',node.Name):
            if not node.Name:
                new_name = 'node' + str(name_index)
                #choose a new name if name is already in tree
                while new_name in names_in_use:
                    name_index += 1
                    new_name = 'node' + str(name_index)
                node.Name = new_name
                names_in_use[node.Name]=1
                name_index += 1


    def getSubTree(self,names):
        """return a new subtree with just the tips in names

        assumes names is a set
        assumes all names in names are present as tips in tree
        """
        tcopy = self.deepcopy()
        
        # unset internal names
        #for n in tcopy.nontips():
        #   n.Name = None
            
            # loop until our tree is the correct size
            # may want to revisit conditional if goes into picrust. unclear if an infinite loop is possible
        while len(tcopy.tips()) != len(names):
            # for each tip, remove it if we do not want to keep it
            for n in tcopy.tips():
                if n.Name not in names:
                    n.Parent.removeNode(n)
                        
            # reduce single-child nodes
            tcopy.prune()
                        
        return tcopy


    def getSubTree_old(self, name_list):
        """A new instance of a sub tree that contains all the otus that are
        listed in name_list.
        just a small change from that in cogent.core.tree.py so that the root
        node keeps its name
        
        Credit: Julia Goodrich
        """
        edge_names = self.getNodeNames(includeself=1, tipsonly=False)
        for name in name_list:
            if name not in edge_names:
                raise ValueError("edge %s not found in tree" % name)
        new_tree = self._getSubTree(name_list)
        if new_tree is None:
            raise TreeError, "no tree created in make sub tree"
        elif new_tree.istip():
            # don't keep name
            new_tree.params = self.params
            new_tree.Length = self.Length
            return new_tree
        else:
            new_tree.Name = self.Name
            new_tree.NameLoaded = self.NameLoaded
            new_tree.params = self.params
            new_tree.Length = self.Length
            # keep unrooted
            if len(self.Children) > 2:
                new_tree = new_tree.unrooted()
            return new_tree

    def _getSubTree(self, included_names, constructor=None):
        """An equivalent node with possibly fewer children, or None
            this is an iterative version of that in cogent.core.tree.py

        Credit: Julia Goodrich
        """
        nodes_stack = [[self, len(self.Children)]]
        result = [[]]

        # Renumber autonamed edges
        if constructor is None:
            constructor = self._default_tree_constructor()

        while nodes_stack:
            top = nodes_stack[-1]
            top_node, num_unvisited_children = top
            if top_node.Name in included_names:
                result[-1].append(top_node.deepcopy(constructor=constructor))
                nodes_stack.pop()
            else:
                #check the top node, any children left unvisited?
                if num_unvisited_children: #has any child unvisited
                    top[1] -= 1  #decrease the #of children unvisited
                    next_child = top_node.Children[-num_unvisited_children]
                    # - for order
                    #pre-visit
                    nodes_stack.append([next_child, len(next_child.Children)])
                    if len(next_child.Children) > 0:
                        result.append([])
                else:
                    node = nodes_stack.pop()[0]
                    children = result[-1]
                    children =[child for child in children if child is not None]
                    if len(top_node.Children) == 0:
                        new_node = None
                    elif len(children) == 0:
                        result.pop()
                        new_node = None
                    elif len(children) == 1:
                        result.pop()
                        # Merge parameter dictionaries by adding lengths and
                        # making weighted averages of other parameters.  This
                        # should probably be moved out of here into a
                        # ParameterSet class (Model?) or tree subclass.
                        params = {}
                        child = children[0]

                        if node.Length is not None and child.Length is not None:
                            shared_params = [n for (n,v) in node.params.items()
                                if v is not None
                                and child.params.get(n) is not None
                                and n is not "length"]
                            length = node.Length + child.Length
                            if length:
                                params = dict([(n,
                                        (node.params[n]*node.Length +
                                        child.params[n]*child.Length) / length)
                                    for n in shared_params])
                            params['length'] = length
                        new_node = child
                        new_node.params = params
                    else:
                        result.pop()
                        new_node = constructor(node, tuple(children))
                    if len(result)>0:
                        result[-1].append(new_node)
                    else:
                        return new_node
