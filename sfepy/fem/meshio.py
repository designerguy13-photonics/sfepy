from sfepy.base.base import *
from sfepy.base.ioutils import skip_read_line, read_token, read_array, read_list, pt
import sfepy.base.la as la
from sfepy.base.progressbar import MyBar
import os.path as op

supported_formats = {
    '.mesh' : 'medit',
    '.vtk'  : 'vtk',
    '.node' : 'tetgen',
    '.txt'  : 'comsol',
    '.h5'   : 'hdf5',
     # Order is important, avs_ucd does not guess -> it is the default.
    '.inp'  : ('abaqus', 'avs_ucd'),
    '.hmascii'  : 'hmascii',
    '.mesh3d'   : 'mesh3d',
    '.bdf'  : 'nastran'
}

##
# c: 15.02.2008, r: 15.02.2008
def sort_by_mat_id( conns_in ):

    # Sort by mat_id within a group, preserve order.
    conns = []
    mat_ids = []
    for ig, conn in enumerate( conns_in ):
        ii = nm.argsort( conn[:,-1], kind = 'mergesort' )
        conn = conn[ii]

        conns.append( conn[:,:-1].copy() )
        mat_ids.append( conn[:,-1].copy() )
    return conns, mat_ids

def sort_by_mat_id2( conns_in, mat_ids_in ):

    # Sort by mat_id within a group, preserve order.
    conns = []
    mat_ids = []
    for ig, conn in enumerate( conns_in ):
        mat_id = mat_ids_in[ig]

        ii = nm.argsort( mat_id, kind = 'mergesort' )
        conns.append( conn[ii] )
        mat_ids.append( mat_id[ii] )

    return conns, mat_ids

##
# conns_in must be sorted by mat_id within a group!
# c: 16.06.2005, r: 15.02.2008
def split_by_mat_id( conns_in, mat_ids_in, descs_in ):

    conns = []
    mat_ids = []
    descs = []

    for ig, conn in enumerate( conns_in ):
        one = nm.array( [-1], nm.int32 )
        ii = la.diff( nm.concatenate( (one, mat_ids_in[ig], one) ) ).nonzero()[0]
        n_gr = len( ii ) - 1;
#        print ii, n_gr
        for igr in range( 0, n_gr ):
            conns.append( conn[ii[igr]:ii[igr+1],:].copy() )
            mat_ids.append( mat_ids_in[ig][ii[igr]:ii[igr+1]] )
            descs.append( descs_in[ig] )

    return (conns, mat_ids, descs)


##
# 12.10.2005, c
def write_bb( fd, array, dtype ):

    fd.write( '3 %d %d %d\n' % (array.shape[1], array.shape[0], dtype) )
    format = ' '.join( ['%.5e'] * array.shape[1] + ['\n'] )

    for row in array:
        fd.write( format % tuple( row ) )

##
# c: 03.10.2005, r: 08.02.2008
def join_conn_groups( conns, descs, mat_ids, concat = False ):
    """Join groups of the same element type."""

    el = dict_from_keys_init( descs, list )
    for ig, desc in enumerate( descs ):
        el[desc].append( ig )
    groups = [ii for ii in el.values() if ii]
##     print el, groups

    descs_out, conns_out, mat_ids_out = [], [], []
    for group in groups:
        n_ep = conns[group[0]].shape[1]

        conn = nm.zeros( (0, n_ep), nm.int32 )
        mat_id = nm.zeros( (0,), nm.int32 )
        for ig in group:
            conn = nm.concatenate( (conn, conns[ig]) )
            mat_id = nm.concatenate( (mat_id, mat_ids[ig]) )

        if concat:
            conn = nm.concatenate( (conn, mat_id[:,nm.newaxis]), 1 )
        else:
            mat_ids_out.append( mat_id )
        conns_out.append( conn )
        descs_out.append( descs[group[0]] )

    if concat:
        return conns_out, descs_out
    else:
        return conns_out, descs_out, mat_ids_out

##
# c: 05.02.2008
class MeshIO( Struct ):
    """
    The abstract class for importing and exporting meshes.

    Read the docstring of the Mesh() class. Basically all you need to do is to
    implement the read() method:

    def read(self, mesh, **kwargs):
        nodes = ...
        conns = ...
        mat_ids = ...
        descs = ...
        mesh._set_data(nodes, conns, mat_ids, descs)
        return mesh

    See the Mesh() class' docstring how the nodes, conns, mat_ids and descs
    should look like. You just need to read them from your specific format from
    disk.

    To write a mesh to disk, just implement the write() method and use the
    information from the mesh instance (e.g. nodes, conns, mat_ids and descs)
    to construct your specific format.

    The methods read_dimension(), read_bounding_box() should be implemented in
    subclasses, as it is often possible to get that kind of information without
    reading the whole mesh file.

    Optionally, subclasses can implement read_data() to read also computation
    results. This concerns mainly the subclasses with implemented write()
    supporting the 'out' kwarg.
    """
    format = None
    call_msg = 'called an abstract MeshIO instance!'

    def __init__( self, filename, **kwargs ):
        Struct.__init__( self, filename = filename, **kwargs )
        self.set_float_format()

    def read_dimension( self, ret_fd = False ):
        raise ValueError(MeshIO.call_msg)

    def read_bounding_box( self, ret_fd = False, ret_dim = False ):
        raise ValueError(MeshIO.call_msg)

    def read( self, mesh, *args, **kwargs ):
        raise ValueError(MeshIO.call_msg)

    def write( self, filename, mesh, *args, **kwargs ):
        raise ValueError(MeshIO.call_msg)

    def read_data( self, step, filename = None ):
        raise ValueError(MeshIO.call_msg)

    def set_float_format( self, format = None ):
        self.float_format = get_default( format, '%e' )

    def get_vector_format( self, dim ):
        return ' '.join( [self.float_format] * dim )
            
##
# c: 05.02.2008
class MeditMeshIO( MeshIO ):
    format = 'medit'

    ##
    # c: 03.07.2008, r: 10.07.2008
    def read_dimension( self, ret_fd = False ):
        fd = open( self.filename, 'r' )
        while 1:
            try:
                line = fd.readline()
            except:
                output( "reading " + fd.name + " failed!" )
                raise
            if len( line ) == 1: continue
            if line[0] == '#': continue
            aux = line.split()
            if aux[0] == 'Dimension':
                if len( aux ) == 2:
                    dim = int( aux[1] )
                else:
                    dim = int( fd.readline() )
                break

        if ret_fd:
            return dim, fd
        else:
            fd.close()
            return dim

    ##
    # c: 22.07.2008
    def read_bounding_box( self, ret_fd = False, ret_dim = False ):
        fd = open( self.filename, 'r' )

        while 1:
            try:
                line = fd.readline()
            except:
                output( "reading " + fd.name + " failed!" )
                raise
            if len( line ) == 0: break
            if len( line ) == 1: continue
            if line[0] == '#': continue
            aux = line.split()
            if (aux[0] == 'Dimension'):
                if len( aux ) == 2:
                    dim = int( aux[1] )
                else:
                    dim = int( fd.readline() )            
            elif (aux[0] == 'Vertices'):
                num = int( read_token( fd ) )
                nod = read_array( fd, num, dim + 1, nm.float64 )
                break

        bbox = nm.vstack( (nm.amin( nod[:,:dim], 0 ),
                           nm.amax( nod[:,:dim], 0 )) )

        if ret_dim:
            if ret_fd:
                return bbox, dim, fd
            else:
                fd.close()
                return bbox, dim
        else:
            if ret_fd:
                return bbox, fd
            else:
                fd.close()
                return bbox

    def read( self, mesh, **kwargs ):
        dim, fd  = self.read_dimension( ret_fd = True )

        conns_in = []
        descs = []
        while 1:
            try:
                line = fd.readline()
                if (len( line ) == 0): break
                if len( line ) == 1: continue
            except EOFError:
                break
            except:
                output( "reading " + fd.name + " failed!" )
                raise
            ls = line.strip()
            if (ls == 'Vertices'):
                num = int( read_token( fd ) )
                nod = read_array( fd, num, dim + 1, nm.float64 )
    ##                 print nod
            elif (ls == 'Tetrahedra'):
                num = int( read_token( fd ) )
                conns_in.append( read_array( fd, num, 5, nm.int32 ) )
                conns_in[-1][:,:-1] -= 1
                descs.append( '3_4' )
            elif (ls == 'Hexahedra'):
                num = int( read_token( fd ) )
                conns_in.append( read_array( fd, num, 9, nm.int32 ) )
                conns_in[-1][:,:-1] -= 1
                descs.append( '3_8' )
            elif (ls == 'Triangles'):
                num = int( read_token( fd ) )
                conns_in.append( read_array( fd, num, 4, nm.int32 ) )
                conns_in[-1][:,:-1] -= 1
                descs.append( '2_3' )
            elif (ls == 'Quadrilaterals'):
                num = int( read_token( fd ) )
                conns_in.append( read_array( fd, num, 5, nm.int32 ) )
                conns_in[-1][:,:-1] -= 1
                descs.append( '2_4' )
            elif ls == 'End':
                break
            elif line[0] == '#':
                continue
            else:
                msg = "corrupted file (line '%s')!" % line
                raise ValueError( msg )
        fd.close()

        conns_in, mat_ids = sort_by_mat_id( conns_in )

        # Detect wedges and pyramides -> separate groups.
        if ('3_8' in descs):
            ic = descs.index( '3_8' )

            conn_in = conns_in.pop( ic )
            flag = nm.zeros( (conn_in.shape[0],), nm.int32 )
            for ii, el in enumerate( conn_in ):
                if (el[4] == el[5]):
                    if (el[5] == el[6]):
                        flag[ii] = 2
                    else:
                        flag[ii] = 1

            conn = []
            desc = []

            ib = nm.where( flag == 0 )[0]
            if (len( ib ) > 0):
                conn.append( conn_in[ib] )
                desc.append( '3_8' )

            iw = nm.where( flag == 1 )[0]
            if (len( iw ) > 0):
                ar = nm.array( [0,1,2,3,4,6,8], nm.int32 )
                conn.append( la.rect( conn_in, iw, ar ) )
                desc.append( '3_6' )

            ip = nm.where( flag == 2 )[0]
            if (len( ip ) > 0):
                ar = nm.array( [0,1,2,3,4,8], nm.int32 )
                conn.append( la.rect( conn_in, ip, ar ) )
                desc.append( '3_5' )

##             print "brick split:", ic, ":", ib, iw, ip, desc

            conns_in[ic:ic] = conn
            del( descs[ic] )
            descs[ic:ic] = desc

        conns, mat_ids, descs = split_by_mat_id( conns_in, mat_ids, descs )
        mesh._set_data( nod[:,:-1], nod[:,-1], conns, mat_ids, descs )

        return mesh

    def write( self, filename, mesh, out = None, **kwargs ):
        fd = open( filename, 'w' )

        coors = mesh.coors
        conns, desc = join_conn_groups( mesh.conns, mesh.descs,
                                      mesh.mat_ids, concat = True )

        n_nod, dim = coors.shape

        fd.write( "MeshVersionFormatted 1\nDimension %d\n" % dim )

        fd.write( "Vertices\n%d\n" % n_nod )
        format = self.get_vector_format( dim ) + ' %d\n'
        for ii in range( n_nod ):
            nn = tuple( coors[ii] ) + (mesh.ngroups[ii],)
            fd.write( format % tuple( nn ) )

        for ig, conn in enumerate( conns ):
            if (desc[ig] == "1_2"):
                fd.write( "Edges\n%d\n" % conn.shape[0] )
                for ii in range( conn.shape[0] ):
                    nn = conn[ii] + 1
                    fd.write( "%d %d %d\n" \
                              % (nn[0], nn[1], nn[2] - 1) )
            elif (desc[ig] == "2_4"):
                fd.write( "Quadrilaterals\n%d\n" % conn.shape[0] )
                for ii in range( conn.shape[0] ):
                    nn = conn[ii] + 1
                    fd.write( "%d %d %d %d %d\n" \
                              % (nn[0], nn[1], nn[2], nn[3], nn[4] - 1) )
            elif (desc[ig] == "2_3"):
                fd.write( "Triangles\n%d\n" % conn.shape[0] )
                for ii in range( conn.shape[0] ):
                    nn = conn[ii] + 1
                    fd.write( "%d %d %d %d\n" % (nn[0], nn[1], nn[2], nn[3] - 1) )
            elif (desc[ig] == "3_4"):
                fd.write( "Tetrahedra\n%d\n" % conn.shape[0] )
                for ii in range( conn.shape[0] ):
                    nn = conn[ii] + 1
                    fd.write( "%d %d %d %d %d\n"
                              % (nn[0], nn[1], nn[2], nn[3], nn[4] - 1) )
            elif (desc[ig] == "3_8"):
                fd.write( "Hexahedra\n%d\n" % conn.shape[0] )
                for ii in range( conn.shape[0] ):
                    nn = conn[ii] + 1
                    fd.write( "%d %d %d %d %d %d %d %d %d\n"
                              % (nn[0], nn[1], nn[2], nn[3], nn[4], nn[5],
                                 nn[6], nn[7], nn[8] - 1) )
            else:
                print 'unknown element type!', desc[ig]
                raise ValueError

        fd.close()

        if out is not None:
            for key, val in out.iteritems():
                raise NotImplementedError


vtk_header = r"""# vtk DataFile Version 2.0
generated by %s
ASCII
DATASET UNSTRUCTURED_GRID
"""
vtk_cell_types = {'2_2' : 3, '2_4' : 9, '2_3' : 5,
                '3_2' : 3, '3_4' : 10, '3_8' : 12 }
vtk_dims = {3 : 2, 9 : 2, 5 : 2, 3 : 3, 10 : 3, 12 : 3}
vtk_inverse_cell_types = {(3, 2) : '2_2', (9, 2) : '2_4', (5, 2) : '2_3',
                       (3, 3) : '3_2', (10, 3) : '3_4', (12, 3) : '3_8' }

##
# c: 05.02.2008
class VTKMeshIO( MeshIO ):
    format = 'vtk'

    def read_coors(self, ret_fd=False):
        fd = open( self.filename, 'r' )
        while 1:
            try:
                line = fd.readline().split()
                if not line: continue
                if line[0] == 'POINTS':
                    n_nod = int( line[1] )
                    coors = read_array( fd, n_nod, -1, nm.float64 )
                    break
            except:
                output( "reading " + fd.name + " failed!" )
                raise

        if ret_fd:
            return coors, fd
        else:
            fd.close()
            return coors
        
    def get_dimension(self, coors):
        dz = nm.diff(coors[:,2])
        if nm.allclose(dz, 0.0):
            dim = 2
        else:
            dim = 3
        return dim

    def read_dimension( self, ret_fd = False ):
        coors, fd = self.read_coors(ret_fd=True)
        dim = self.get_dimension(coors)
        if ret_fd:
            return dim, fd
        else:
            fd.close()
            return dim

    ##
    # c: 22.07.2008
    def read_bounding_box( self, ret_fd = False, ret_dim = False ):
        coors, fd = self.read_coors(ret_fd=ret_fd)
        dim = self.get_dimension(coors)
        
        bbox = nm.vstack( (nm.amin( coors[:,:dim], 0 ),
                           nm.amax( coors[:,:dim], 0 )) )

        if ret_dim:
            if ret_fd:
                return bbox, dim, fd
            else:
                fd.close()
                return bbox, dim
        else:
            if ret_fd:
                return bbox, fd
            else:
                fd.close()
                return bbox

    ##
    # c: 05.02.2008, r: 10.07.2008
    def read( self, mesh, **kwargs ):
        fd = open( self.filename, 'r' )
        mode = 'header'
        mode_status = 0
        coors = conns = desc = mat_id = None
        while 1:
            try:
                line = fd.readline()
                if len( line ) == 0: break
                elif len( line ) == 1: continue
                if line[0] == '#': continue
            except EOFError:
                break
            except:
                output( "reading " + fd.name + " failed!" )
                raise

            if mode == 'header':
                if mode_status == 0:
                    if line.strip() == 'ASCII':
                        mode_status = 1
                elif mode_status == 1:
                    if line.strip() == 'DATASET UNSTRUCTURED_GRID':
                        mode_status = 0
                        mode = 'points'

            elif mode == 'points':
                line = line.split()
                if line[0] == 'POINTS':
                    n_nod = int( line[1] )
                    coors = read_array( fd, n_nod, -1, nm.float64 )
                    mode = 'cells'

            elif mode == 'cells':
                line = line.split()
                if line[0] == 'CELLS':
                    n_el, n_val = map( int, line[1:3] )
                    raw_conn = read_list( fd, n_val, int )
                    mode = 'cell_types'

            elif mode == 'cell_types':
                line = line.split()
                if line[0] == 'CELL_TYPES':
                    assert_( int( line[1] ) == n_el )
                    cell_types = read_array( fd, n_el, -1, nm.int32 )
                    mode = 'mat_id'

            elif mode == 'mat_id':
                if mode_status == 0:
                    line = line.split()
                    if line[0] == 'CELL_DATA':
                        assert_( int( line[1] ) == n_el )
                        mode_status = 1
                elif mode_status == 1:
                    if line.strip() == 'SCALARS mat_id float 1':
                        mode_status = 2
                elif mode_status == 2:
                    if line.strip() == 'LOOKUP_TABLE default':
                        mat_id = read_list( fd, n_el, int )
                        mode_status = 0
                        mode = 'finished'
            elif mode == 'finished':
                break
        fd.close()
 
        if mat_id is None:
            mat_id = [[0]] * n_el

        dim = self.get_dimension(coors)
        if dim == 2:
            coors = coors[:,:2]
        coors = nm.ascontiguousarray( coors )

        cell_types = cell_types.squeeze()

        dconns = {}
        for iel, row in enumerate( raw_conn ):
            ct = cell_types[iel]
            key = (ct, dim)
            if key not in vtk_inverse_cell_types:
                continue
            if (ct == 3) or (vtk_dims[ct] != dim): # No bar elements yet.
                continue
            ct = vtk_inverse_cell_types[key]
            dconns.setdefault( ct, [] ).append( row[1:] + mat_id[iel] )

        desc = []
        conns = []
        for key, conn in dconns.iteritems():
            desc.append( key )
            conns.append( nm.array( conn, dtype = nm.int32 ) )

        conns_in, mat_ids = sort_by_mat_id( conns )
        conns, mat_ids, descs = split_by_mat_id( conns_in, mat_ids, desc )

        mesh._set_data( coors, None, conns, mat_ids, descs )

        return mesh

    def write( self, filename, mesh, out = None, **kwargs ):

        fd = open( filename, 'w' )
        fd.write( vtk_header % op.basename( sys.argv[0] ) )

        n_nod, dim = mesh.coors.shape
        sym = dim * (dim + 1) / 2

        fd.write( '\nPOINTS %d float\n' % n_nod )

        aux = mesh.coors
        if dim == 2:
            aux = nm.hstack((aux, nm.zeros((aux.shape[0], 1), dtype=aux.dtype)))

        format = self.get_vector_format( 3 ) + '\n'
        for row in aux:
            fd.write( format % tuple( row ) )

        n_el, n_els, n_e_ps = mesh.n_el, mesh.n_els, mesh.n_e_ps
        total_size = nm.dot( n_els, n_e_ps + 1 )
        fd.write( '\nCELLS %d %d\n' % (n_el, total_size) )

        ct = []
        for ig, conn in enumerate( mesh.conns ):
            nn = n_e_ps[ig] + 1
            ct += [vtk_cell_types[mesh.descs[ig]]] * n_els[ig]
            format = ' '.join( ['%d'] * nn + ['\n'] )

            for row in conn:
                fd.write( format % ((nn-1,) + tuple( row )) )

        fd.write( '\nCELL_TYPES %d\n' % n_el )
        fd.write( ''.join( ['%d\n' % ii for ii in ct] ) )

        fd.write( '\nPOINT_DATA %d\n' % n_nod )

        # node groups
        fd.write( '\nSCALARS node_groups int 1\nLOOKUP_TABLE default\n' )
        fd.write( ''.join( ['%d\n' % ii for ii in mesh.ngroups] ) )

        if out is not None:
            point_keys = [key for key, val in out.iteritems()
                          if val.mode == 'vertex']
        else:
            point_keys = {}
            
        for key in point_keys:
            val = out[key]
            nr, nc = val.data.shape

            if nc == 1:
                fd.write( '\nSCALARS %s float %d\n' % (key, nc) )
                fd.write( 'LOOKUP_TABLE default\n' )

                format = self.float_format + '\n'
                for row in val.data:
                    fd.write( format % row )

            elif nc == dim:
                fd.write( '\nVECTORS %s float\n' % key )
                if dim == 2:
                    aux = nm.hstack( (val.data,
                                      nm.zeros( (nr, 1), dtype = nm.float64 ) ) )
                else:
                    aux = val.data

                format = self.get_vector_format( 3 ) + '\n'
                for row in aux:
                    fd.write( format % tuple( row ) )

            else:
                raise NotImplementedError, nc

        if out is not None:
            cell_keys = [key for key, val in out.iteritems()
                         if val.mode == 'cell']
        else:
            cell_keys = {}
            
        fd.write( '\nCELL_DATA %d\n' % n_el )

        # cells - mat_id
        fd.write( 'SCALARS mat_id int 1\nLOOKUP_TABLE default\n' )
        aux = nm.hstack(mesh.mat_ids).tolist() 
        fd.write( ''.join( ['%d\n' % ii for ii in aux] ) )

        for key in cell_keys:
            val = out[key]
            ne, aux, nr, nc = val.data.shape

            if (nr == 1) and (nc == 1):
                fd.write( '\nSCALARS %s float %d\n' % (key, nc) )
                fd.write( 'LOOKUP_TABLE default\n' )
                format = self.float_format + '\n'
                for row in val.data.squeeze():
                    fd.write( format % row )

            elif (nr == dim) and (nc == 1):
                fd.write( '\nVECTORS %s float\n' % key )
                if dim == 2:
                    aux = nm.hstack( (val.data.squeeze(),
                                      nm.zeros( (ne, 1), dtype = nm.float64 ) ) )
                else:
                    aux = val.data

                format = self.get_vector_format( 3 ) + '\n'
                for row in aux:
                    fd.write( format % tuple( row.squeeze() ) )

            elif (((nr == sym) or (nr == (dim * dim))) and (nc == 1)) \
                     or ((nr == dim) and (nc == dim)):
                # Below not tested!!!
                fd.write( '\nTENSORS %s float\n' % key );
                data = val.data.squeeze()

                if dim == 3:
                    if nr == sym:
                        aux = data[:,[0,3,4,3,1,5,4,5,2]]
                    elif nr == (dim * dim):
                        aux = data[:,[0,3,4,6,1,5,7,8,2]]
                    else:
                        aux = data.reshape((data.shape[0], dim*dim))
                else:
                    zz = nm.zeros( (data.shape[0], 1), dtype = nm.float64 );
                    if nr == sym:
                        aux = nm.c_[data[:,[0,2]], zz, data[:,[2,1]],
                                    zz, zz, zz, zz]
                    elif nr == (dim * dim):
                        aux = nm.c_[data[:,[0,2]], zz, data[:,[3,1]],
                                    zz, zz, zz, zz]
                    else:
                        aux = nm.c_[data[:,0,[0,1]], zz, data[:,1,[0,1]],
                                    zz, zz, zz, zz]

                format = self.get_vector_format( 3 )
                format = '\n'.join( [format] * 3 ) + '\n\n';
                for row in aux:
                    fd.write( format % tuple( row ) )

            else:
                raise NotImplementedError, (nr, nc)

        fd.close()

    def read_data( self, step, filename = None ):
        """Point data only!"""
        filename = get_default( filename, self.filename )

        out = {}
        
        fd = open( self.filename, 'r' )
        while 1:
            line = fd.readline().split()
            if not line: continue
            if line[0] == 'POINT_DATA':
                break

        n_nod = int(line[1])
        
        line = fd.readline()
        while 1:
            if not line:
                break
            # Skip empty lines.
            line = line.split()
            while not line:
                line = fd.readline().split()

            if line[0] == 'SCALARS':
                name, dtype, nc = line[1:]
                assert_(int(nc) == 1)
                fd.readline() # skip lookup table line
                
                data = nm.zeros((n_nod,), dtype=nm.float64)
                ii = 0
                while ii < n_nod:
                    data[ii] = float(fd.readline())
                    ii += 1

                out[name] = Struct( name = name,
                                    mode = 'vertex',
                                    data = data,
                                    dofs = None )

            elif line[0] == 'VECTORS':
                name, dtype = line[1:]
                data = []
                ii = 0
                while ii < n_nod:
                    data.append([float(val) for val in fd.readline().split()])
                    ii += 1

                out[name] = Struct( name = name,
                                    mode = 'vertex',
                                    data = nm.array(data, dtype=nm.float64),
                                    dofs = None )

            elif line[0] == 'CELL_DATA':
                break

            line = fd.readline()

        fd.close()

        return out

##
# c: 15.02.2008
class TetgenMeshIO( MeshIO ):
    format = "tetgen"

    ##
    # c: 15.02.2008, r: 15.02.2008
    def read( self, mesh, **kwargs ):
        import os
        fname = os.path.splitext(self.filename)[0]
        nodes=self.getnodes(fname+".node", MyBar("       nodes:"))
        elements, regions = self.getele(fname+".ele", MyBar("       elements:"))
        descs = []
        conns = []
        mat_ids = []
        elements = nm.array( elements, dtype = nm.int32 )-1
        for key, value in regions.iteritems():
            descs.append( "3_4" )
            mat_ids.append( nm.ones_like(value) * key )
            conns.append( elements[nm.array(value)-1].copy() )

        mesh._set_data( nodes, None, conns, mat_ids, descs )
        return mesh

    ##
    # c: 15.02.2008, r: 15.02.2008
    @staticmethod
    def getnodes(fnods, up, verbose=True):
        """
        Reads t.1.nodes, returns a list of nodes.

        Example:

        >>> self.getnodes("t.1.node", MyBar("nodes:"))
        [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (0.0, 4.0, 0.0), (-4.0, 0.0, 0.0),
        (0.0, 0.0, 4.0), (0.0, -4.0, 0.0), (0.0, -0.0, -4.0), (-2.0, 0.0,
        -2.0), (-2.0, 2.0, 0.0), (0.0, 2.0, -2.0), (0.0, -2.0, -2.0), (2.0,
        0.0, -2.0), (2.0, 2.0, 0.0), ... ]

        """
        f=open(fnods)
        l=[int(x) for x in f.readline().split()]
        npoints,dim,nattrib,nbound=l
        assert_( dim==3 )
        if verbose: up.init(npoints)
        nodes=[]
        for line in f:
            if line[0]=="#": continue
            l=[float(x) for x in line.split()]
            assert_( int(l[0])==len(nodes)+1 )
            l = l[1:]
            nodes.append(tuple(l))
            if verbose: up.update(len(nodes))
        assert_( npoints==len(nodes) )
        return nodes

    ##
    # c: 15.02.2008, r: 15.02.2008
    @staticmethod
    def getele(fele, up, verbose=True):
        """
        Reads t.1.ele, returns a list of elements.

        Example:

        >>> elements, regions = self.getele("t.1.ele", MyBar("elements:"))
        >>> elements
        [(20, 154, 122, 258), (86, 186, 134, 238), (15, 309, 170, 310), (146,
        229, 145, 285), (206, 207, 125, 211), (99, 193, 39, 194), (185, 197,
        158, 225), (53, 76, 74, 6), (19, 138, 129, 313), (23, 60, 47, 96),
        (119, 321, 1, 329), (188, 296, 122, 322), (30, 255, 177, 256), ...]
        >>> regions
        {100: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18,
        19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36,
        37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54,
        55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 7, ...],
        ...}

        """
        f=file(fele)
        l=[int(x) for x in f.readline().split()]
        ntetra,nnod,nattrib=l
        #we have either linear or quadratic tetrahedra:
        assert_( nnod in [4,10] )
        linear= (nnod==4)
        if not linear:
            raise Exception("Only linear tetrahedra reader is implemented")
        if verbose: up.init(ntetra)
        if nattrib!=1:
            raise "tetgen didn't assign an entity number to each element \
(option -A)"
        els=[]
        regions={}
        for line in f:
            if line[0]=="#": continue
            l=[int(x) for x in line.split()]
            assert_( len(l)-2 == 4 )
            els.append((l[1],l[2],l[3],l[4]))
            regionnum=l[5]
            if regionnum==0:
                print "see %s, element # %d"%(fele,l[0])
                raise "there are elements not belonging to any physical entity"
            if regions.has_key(regionnum):
                regions[regionnum].append(l[0])
            else:
                regions[regionnum]=[l[0]]
            assert_( l[0]==len(els) )
            if verbose: up.update(l[0])
        return els, regions

    ##
    # c: 26.03.2008, r: 26.03.2008
    def write( self, filename, mesh, out = None, **kwargs ):
        raise NotImplementedError

    def read_dimension(self):
        # TetGen only supports 3D mesh
        return 3

    ##
    # c: 22.07.2008
    def read_bounding_box( self ):
        raise NotImplementedError

##
# c: 20.03.2008
class ComsolMeshIO( MeshIO ):
    format = 'comsol'

    ##
    # c: 20.03.2008, r: 20.03.2008
    def _read_commented_int( self ):
        return int( skip_read_line( self.fd ).split( '#' )[0] )

    ##
    # c: 20.03.2008, r: 20.03.2008
    def read( self, mesh, **kwargs ):

        self.fd = fd = open( self.filename, 'r' )
        mode = 'header'

        coors = conns = desc = None
        while 1:
            if mode == 'header':
                line = skip_read_line( fd )

                n_tags = self._read_commented_int()
                for ii in xrange( n_tags ):
                    skip_read_line( fd )
                n_types = self._read_commented_int()
                for ii in xrange( n_types ):
                    skip_read_line( fd )

                skip_read_line( fd )
                assert_( skip_read_line( fd ).split()[1] == 'Mesh' )
                skip_read_line( fd )
                dim = self._read_commented_int()
                assert_( (dim == 2) or (dim == 3) )
                n_nod = self._read_commented_int()
                i0 = self._read_commented_int()
                mode = 'points'

            elif mode == 'points':
                coors = read_array( fd, n_nod, dim, nm.float64 )
                mode = 'cells'

            elif mode == 'cells':

                n_types = self._read_commented_int()
                conns = []
                descs = []
                mat_ids = []
                for it in xrange( n_types ):
                    t_name = skip_read_line( fd ).split()[1]
                    n_ep = self._read_commented_int()
                    n_el = self._read_commented_int()
                    if dim == 2:
                        aux = read_array( fd, n_el, n_ep, nm.int32 )
                        if t_name == 'tri':
                            conns.append( aux )
                            descs.append( '2_3' )
                            is_conn = True
                        else:
                            is_conn = False
                    else:
                        raise NotImplementedError

                    # Skip parameters.
                    n_pv = self._read_commented_int()
                    n_par = self._read_commented_int()
                    for ii in xrange( n_par ):
                        skip_read_line( fd )

                    n_domain = self._read_commented_int()
                    assert_( n_domain == n_el )
                    if is_conn:
                        mat_id = read_array( fd, n_domain, 1, nm.int32 )
                        mat_ids.append( mat_id )
                    else:
                        for ii in xrange( n_domain ):
                            skip_read_line( fd )

                    # Skip up/down pairs.
                    n_ud = self._read_commented_int()
                    for ii in xrange( n_ud ):
                        skip_read_line( fd )
                break

        fd.close()
        self.fd = None

        conns2 = []
        for ii, conn in enumerate( conns ):
            conns2.append( nm.c_[conn, mat_ids[ii]] )

        conns_in, mat_ids = sort_by_mat_id( conns2 )
        conns, mat_ids, descs = split_by_mat_id( conns_in, mat_ids, descs )
        mesh._set_data( coors, None, conns, mat_ids, descs )
        
        return mesh

    ##
    # c: 20.03.2008, r: 20.03.2008
    def write( self, filename, mesh, out = None, **kwargs ):
        raise NotImplementedError

##
# c: 23.06.2008
class HDF5MeshIO( MeshIO ):
    format = "hdf5"

    import string
    _all = ''.join( map( chr, range( 256 ) ) )
    _letters = string.letters + string.digits + '_'
    _rubbish = ''.join( [ch for ch in set( _all ) - set( _letters )] )
    _tr = string.maketrans( _rubbish, '_' * len( _rubbish ) )

    def read( self, mesh, **kwargs ):
        fd = pt.openFile( self.filename, mode = "r" )

        mesh_group = fd.root.mesh

        mesh.name = mesh_group.name.read()
        coors = mesh_group.coors.read()
        ngroups = mesh_group.ngroups.read()

        n_gr =  mesh_group.n_gr.read()

        conns = []
        descs = []
        mat_ids = []
        for ig in xrange( n_gr ):
            gr_name = 'group%d' % ig
            group = mesh_group._f_getChild( gr_name )
            conns.append( group.conn.read() )
            mat_ids.append( group.mat_id.read() )
            descs.append( group.desc.read() )

        fd.close()
        mesh._set_data( coors, ngroups, conns, mat_ids, descs )

        return mesh

    def write( self, filename, mesh, out = None, ts = None, **kwargs ):
        from time import asctime

        if pt is None:
            output( 'pytables not imported!' )
            raise ValueError

        step = get_default_attr( ts, 'step', 0 )
        if step == 0:
            # A new file.
            fd = pt.openFile( filename, mode = "w",
                              title = "SfePy output file" )

            mesh_group = fd.createGroup( '/', 'mesh', 'mesh' )

            fd.createArray( mesh_group, 'name', mesh.name, 'name' )
            fd.createArray( mesh_group, 'coors', mesh.coors, 'coors' )
            fd.createArray( mesh_group, 'ngroups', mesh.ngroups, 'ngroups' )
            fd.createArray( mesh_group, 'n_gr', len( mesh.conns ), 'n_gr' )
            for ig, conn in enumerate( mesh.conns ):
                conn_group = fd.createGroup( mesh_group, 'group%d' % ig,
                                            'connectivity group' )
                fd.createArray( conn_group, 'conn', conn, 'connectivity' )
                fd.createArray( conn_group, 'mat_id', mesh.mat_ids[ig], 'material id' )
                fd.createArray( conn_group, 'desc', mesh.descs[ig], 'element Type' )

            if ts is not None:
                ts_group = fd.createGroup( '/', 'ts', 'time stepper' )
                fd.createArray( ts_group, 't0', ts.t0, 'initial time' )
                fd.createArray( ts_group, 't1', ts.t1, 'final time'  )
                fd.createArray( ts_group, 'dt', ts.dt, 'time step' )
                fd.createArray( ts_group, 'n_step', ts.n_step, 'n_step' )

            tstat_group = fd.createGroup( '/', 'tstat', 'global time statistics' )
            fd.createArray( tstat_group, 'created', asctime(),
                            'file creation time' )
            fd.createArray( tstat_group, 'finished', '.' * 24,
                            'file closing time' )

            fd.createArray( fd.root, 'last_step', nm.array( [0], dtype = nm.int32 ),
                            'last saved step' )

            fd.close()

        if out is not None:
            if ts is None:
                step, time, nt  = 0, 0.0, 0.0
            else:
                step, time, nt = ts.step, ts.time, ts.nt

            # Existing file.
            fd = pt.openFile( filename, mode = "r+" )

            step_group = fd.createGroup( '/', 'step%d' % step, 'time step data' )
            name_dict = {}
            for key, val in out.iteritems():
    #            print key
                dofs = get_default(val.dofs, (-1,))
                var_name = val.get_default_attr('var_name', 'None')

                group_name = '_' + key.translate( self._tr )
                data_group = fd.createGroup(step_group, group_name,
                                            '%s data' % key)
                fd.createArray( data_group, 'data', val.data, 'data' )
                fd.createArray( data_group, 'mode', val.mode, 'mode' )
                fd.createArray( data_group, 'dofs', dofs, 'dofs' )
                fd.createArray( data_group, 'name', val.name, 'object name' )
                fd.createArray( data_group, 'var_name',
                                var_name, 'object parent name' )
                fd.createArray( data_group, 'dname', key, 'data name' )
                name_dict[key] = group_name

            step_group._v_attrs.name_dict = name_dict
            fd.root.last_step[0] = step

            fd.removeNode( fd.root.tstat.finished )
            fd.createArray( fd.root.tstat, 'finished', asctime(),
                            'file closing time' )
            fd.close()

    def read_last_step(self, filename=None):
        filename = get_default( filename, self.filename )
        fd = pt.openFile( filename, mode = "r" )
        last_step = fd.root.last_step[0]
        fd.close()
        return last_step

    def read_time_stepper( self, filename = None ):
        filename = get_default( filename, self.filename )
        fd = pt.openFile( filename, mode = "r" )

        ts_group = fd.root.ts
        out =  (ts_group.t0.read(), ts_group.t1.read(),
                ts_group.dt.read(), ts_group.n_step.read())
        fd.close()
        return out

    def _get_step_group( self, step, filename = None ):
        filename = get_default( filename, self.filename )
        fd = pt.openFile( filename, mode = "r" )

        gr_name = 'step%d' % step
        try:
            step_group = fd.getNode( fd.root, gr_name )
        except:
            output( 'step %d data not found - premature end of file?' % step )
            fd.close()
            return None, None

        return fd, step_group

    def read_data( self, step, filename = None ):
        fd, step_group = self._get_step_group( step, filename = filename )
        if fd is None: return None

        out = {}
        for data_group in step_group:
            key = data_group.dname.read()
            out[key] = Struct( name = data_group.name.read(),
                               mode = data_group.mode.read(),
                               data = data_group.data.read(),
                               dofs = tuple( data_group.dofs.read() ) )
            if out[key].dofs == (-1,):
                out[key].dofs = None

        fd.close()

        return out

    def read_data_header( self, dname, step = 0, filename = None ):
        fd, step_group = self._get_step_group( step, filename = filename )
        if fd is None: return None

        groups = step_group._v_groups
        for name, data_group in groups.iteritems():
            key = data_group.dname.read()
            if key == dname:
                mode = data_group.mode.read()
                fd.close()
                return mode, name

        fd.close()
        raise KeyError, 'non-existent data: %s' % dname

    def read_time_history( self, node_name, indx, filename = None ):
        filename = get_default( filename, self.filename )
        fd = pt.openFile( filename, mode = "r" )

        th = dict_from_keys_init( indx, list )
        for step in xrange( fd.root.last_step[0] + 1 ):
            gr_name = 'step%d' % step

            step_group = fd.getNode( fd.root, gr_name )
            data = step_group._f_getChild( node_name ).data

            for ii in indx:
                th[ii].append( nm.array( data[ii] ) )

        fd.close()

        for key, val in th.iteritems():
            aux = nm.array( val )
            if aux.ndim == 4: # cell data.
                aux = aux[:,0,:,0]
            th[key] = aux

        return th

    def read_variables_time_history( self, var_names, ts, filename = None ):
        filename = get_default( filename, self.filename )
        fd = pt.openFile( filename, mode = "r" )

        assert_( (fd.root.last_step[0] + 1) == ts.n_step )

        ths = dict_from_keys_init( var_names, list )

        arr = nm.asarray
        for step in xrange( ts.n_step ):
            gr_name = 'step%d' % step
            step_group = fd.getNode( fd.root, gr_name )
            name_dict = step_group._v_attrs.name_dict
            for var_name in var_names:
                data = step_group._f_getChild( name_dict[var_name] ).data
                ths[var_name].append( arr( data.read() ) )

        fd.close()

        return ths

class Mesh3DMeshIO( MeshIO ):
    format = "mesh3d"

    def read(self, mesh, **kwargs):
        f = open(self.filename)
        # read the whole file:
        vertices = self._read_section(f, integer=False)
        tetras = self._read_section(f)
        hexes = self._read_section(f)
        prisms = self._read_section(f)
        tris = self._read_section(f)
        quads = self._read_section(f)

        # substract 1 from all elements, because we count from 0:
        conns = []
        mat_ids = []
        descs = []
        if len(tetras) > 0:
            conns.append(tetras - 1)
            mat_ids.append([0]*len(tetras))
            descs.append("3_4")
        if len(hexes) > 0:
            conns.append(hexes - 1)
            mat_ids.append([0]*len(hexes))
            descs.append("3_8")
        mesh._set_data( vertices, None, conns, mat_ids, descs )
        return mesh

    def read_dimension(self):
        return 3

    def _read_line(self, f):
        """
        Reads one non empty line (if it's a comment, it skips it).
        """
        l = f.readline().strip()
        while l == "" or l[0] == "#": # comment or an empty line
            l = f.readline().strip()
        return l

    def _read_section(self, f, integer=True):
        """
        Reads one section from the mesh3d file.

        integer ... if True, all numbers are passed to int(), otherwise to
            float(), before returning

        Some examples how a section can look like:

        2
        1 2 5 4 7 8 11 10
        2 3 6 5 8 9 12 11

        or

        5
        1 2 3 4     1
        1 2 6 5     1
        2 3 7 6     1
        3 4 8 7     1
        4 1 5 8     1

        or

        0

        """
        if integer:
            dtype=int
        else:
            dtype=float
        l = self._read_line(f)
        N = int(l)
        rows = []
        for i in range(N):
            l = self._read_line(f)
            row = nm.fromstring(l, sep=" ", dtype=dtype)
            rows.append(row)
        return nm.array(rows)

def mesh_from_tetra_hexa( mesh, ids, coors, ngroups,
                          tetras, mat_tetras,
                          hexas, mat_hexas ):
    ids = nm.asarray( ids, dtype = nm.int32 )
    coors = nm.asarray( coors, dtype = nm.float64 )

    n_nod = coors.shape[0]
    
    remap = nm.zeros( (ids.max()+1,), dtype = nm.int32 )
    remap[ids] = nm.arange( n_nod, dtype=nm.int32 )

    tetras = remap[nm.array( tetras, dtype = nm.int32 )]
    hexas = remap[nm.array( hexas, dtype = nm.int32 )]

    conns = [tetras, hexas]
    mat_ids = [nm.array( ar, dtype = nm.int32 )
               for ar in [mat_tetras, mat_hexas]]
    descs = ['3_4', '3_8']

    conns, mat_ids = sort_by_mat_id2( conns, mat_ids )
    conns, mat_ids, descs = split_by_mat_id( conns, mat_ids, descs )
    mesh._set_data( coors, ngroups, conns, mat_ids, descs )
    return mesh

class AVSUCDMeshIO( MeshIO ):
    format = 'avs_ucd'

    def guess( filename ):
        return True
    guess = staticmethod( guess )
    
    def read( self, mesh, **kwargs ):
        fd = open( self.filename, 'r' )

        # Skip all comments.
        while 1:
            line = fd.readline()
            if line and (line[0] != '#'):
                break

        header = [int(ii) for ii in line.split()]
        n_nod, n_el = header[0:2]

        ids = nm.zeros( (n_nod,), dtype = nm.int32 )
        dim = 3
        coors = nm.zeros( (n_nod, dim), dtype = nm.float64 )
        for ii in xrange( n_nod ):
            line = fd.readline().split()
            ids[ii] = int( line[0] )
            coors[ii] = [float( coor ) for coor in line[1:]]

        
        mat_tetras = []
        tetras = []
        mat_hexas = []
        hexas = []
        for ii in xrange( n_el ):
            line = fd.readline().split()
            if line[2] == 'tet':
                mat_tetras.append( int( line[1] ) )
                tetras.append( [int( ic ) for ic in line[3:]] )
            elif line[2] == 'hex':
                mat_hexas.append( int( line[1] ) )
                hexas.append( [int( ic ) for ic in line[3:]] )
        fd.close()

        mesh = mesh_from_tetra_hexa( mesh, ids, coors, None,
                                     tetras, mat_tetras,
                                     hexas, mat_hexas )
        return mesh

    def read_dimension(self):
        return 3

    def write( self, filename, mesh, out = None, **kwargs ):
        raise NotImplementedError

class HypermeshAsciiMeshIO( MeshIO ):
    format = 'hmascii'

    def read( self, mesh, **kwargs ):
        fd = open( self.filename, 'r' )

        ids = []
        coors = []
        tetras = []
        mat_tetras = []
        hexas = []
        mat_hexas = []

        for line in fd:
            if line and (line[0] == '*'):
                if line[1:5] == 'node':
                    line = line.strip()[6:-1].split(',')
                    ids.append( int( line[0] ) )
                    coors.append( [float( coor ) for coor in line[1:4]] )

                elif line[1:7] == 'tetra4':
                    line = line.strip()[8:-1].split(',')
                    mat_tetras.append( int( line[1] ) )
                    tetras.append( [int( ic ) for ic in line[2:6]] )

                elif line[1:6] == 'hexa8':
                    line = line.strip()[7:-1].split(',')
                    mat_hexas.append( int( line[1] ) )
                    hexas.append( [int( ic ) for ic in line[2:10]] )
        fd.close()

        mesh = mesh_from_tetra_hexa( mesh, ids, coors, None,
                                     tetras, mat_tetras,
                                     hexas, mat_hexas )

        return mesh

    def read_dimension(self):
        return 3

    def write( self, filename, mesh, out = None, **kwargs ):
        raise NotImplementedError

class AbaqusMeshIO( MeshIO ):
    format = 'abaqus'

    def guess( filename ):
        ok = False
        fd = open( filename, 'r' )
        for ii in xrange(100):
            try:
                line = fd.readline().strip().split(',')
            except:
                break
            if line[0] == '*NODE':
                ok = True
                break
        fd.close()
        
        return ok
    guess = staticmethod( guess )


    def read( self, mesh, **kwargs ):
        fd = open( self.filename, 'r' )

        ids = []
        coors = []
        tetras = []
        mat_tetras = []
        hexas = []
        mat_hexas = []
        nsets = {}
        ing = 1

        line = fd.readline().split(',')
        while 1:
            if not line[0]: break

            token = line[0].strip().lower()
            if token == '*node':
                while 1:
                    line = fd.readline().split(',')
                    if (not line[0]) or (line[0][0] == '*'): break
                    ids.append( int( line[0] ) )
                    coors.append( [float( coor ) for coor in line[1:4]] )

            elif token == '*element':

                if line[1].find( 'C3D8' ) >= 0:
                    while 1:
                        line = fd.readline().split(',')
                        if (not line[0]) or (line[0][0] == '*'): break
                        mat_hexas.append( 0 )
                        hexas.append( [int( ic ) for ic in line[1:9]] )

                elif line[1].find( 'C3D4' ) >= 0:
                    while 1:
                        line = fd.readline().split(',')
                        if (not line[0]) or (line[0][0] == '*'): break
                        mat_tetras.append( 0 )
                        tetras.append( [int( ic ) for ic in line[1:5]] )

                else:
                    raise ValueError('unknown element type! (%s)' % line[1])

            elif token == '*nset':

                if line[-1].strip() == 'GENERATE':
                    line = fd.readline()
                    continue

                while 1:
                    line = fd.readline().strip().split(',')
                    if (not line[0]) or (line[0][0] == '*'): break
                    if not line[-1]: line = line[:-1]
                    aux = [int( ic ) for ic in line]
                    nsets.setdefault(ing, []).extend( aux )
                ing += 1

            else:
                line = fd.readline().split(',')
                
        fd.close()

        ngroups = nm.zeros( (len(coors),), dtype = nm.int32 )
        for ing, ii in nsets.iteritems():
            ngroups[nm.array(ii)-1] = ing

        mesh = mesh_from_tetra_hexa( mesh, ids, coors, ngroups,
                                     tetras, mat_tetras,
                                     hexas, mat_hexas )
        return mesh

    def read_dimension(self):
        return 3

    def write( self, filename, mesh, out = None, **kwargs ):
        raise NotImplementedError
    
class BDFMeshIO( MeshIO ):
    format = 'nastran'

    def read_dimension( self, ret_fd = False ):
        fd = open( self.filename, 'r' )
        el3d = 0
        while 1:
            try:
                line = fd.readline()
            except:
                output( "reading " + fd.name + " failed!" )
                raise
            if len( line ) == 1: continue
            if line[0] == '$': continue
            aux = line.split()
            
            if aux[0] == 'CHEXA':
                el3d += 1
            elif row[0] == 'CTETRA':
                el3d += 1

        if el3d > 0:
            dim = 3
        else:
            dim = 2

        if ret_fd:
            return dim, fd
        else:
            fd.close()
            return dim

    def read( self, mesh, **kwargs ):
        import string
        fd = open( self.filename, 'r' )

        el = {'3_8' : [], '3_4' : [], '2_4' : [], '2_3' : []}
        nod = []
        cmd = ''
        dim = 2

        conns_in = []
        descs = []
        while 1:
            try:
                line = fd.readline()
            except EOFError:
                break
            except:
                output( "reading " + fd.name + " failed!" )
                raise

            if (len( line ) == 0): break
            if len( line ) == 1: continue
            if line[0] == '$': continue

            row = line.strip().split()

            if row[0] == 'GRID*':
                aux = row[1:4];
                cmd = 'GRIDX';
            elif row[0] == 'CHEXA':
                aux = [int(ii)-1 for ii in row[3:9]]
                aux2 = int(row[2])
                aux3 = row[9]
                cmd ='CHEXAX'
            elif row[0] == 'CTETRA':
                aux = [int(ii)-1 for ii in row[3:]]
                aux.append( int(row[2]) )
                el['3_4'].append( aux )
                dim = 3
            elif row[0] == 'CQUAD4':
                aux = [int(ii)-1 for ii in row[3:]]
                aux.append( int(row[2]) )
                el['2_4'].append( aux )
            elif row[0] == 'CTRIA3':
                aux = [int(ii)-1 for ii in row[3:]]
                aux.append( int(row[2]) )
                el['2_3'].append( aux )
            elif cmd == 'GRIDX':
                cmd = ''
                aux2 = row[1]
                if aux2[-1] == '0':
                    aux2 = aux2[:-1]
                    aux3 = aux[1:]
                    aux3.append( aux2 )
                    nod.append( [float(ii) for ii in aux3] );
            elif cmd == 'CHEXAX':
                cmd = ''
                aux4 = row[0]
                aux5 = string.find( aux4, aux3 )
                aux.append( int(aux4[(aux5+len(aux3)):])-1 )
                aux.extend( [int(ii)-1 for ii in row[1:]] )
                aux.append( aux2 )
                el['3_8'].append( aux )
                dim = 3
                
        for elem in el.keys():
            if len(el[elem]) > 0:
                conns_in.append( el[elem] )
                descs.append( elem )

        fd.close()

        nod = nm.array( nod, nm.float64 )
        if dim == 2:
            nod = nod[:,:2].copy()
        conns_in = nm.array( conns_in, nm.int32 )
        
        conns_in, mat_ids = sort_by_mat_id( conns_in )
        conns, mat_ids, descs = split_by_mat_id( conns_in, mat_ids, descs )
        mesh._set_data( nod, None, conns, mat_ids, descs )

        return mesh

    def write( self, filename, mesh, out = None, **kwargs ):
        raise NotImplementedError

def guess_format( filename, ext, formats, io_table ):
    """
    Guess the format of filename, candidates are in formats.
    """
    ok = False
    for format in formats:
        output( 'guessing %s' % format )
        try:
            ok = io_table[format].guess( filename )
        except AttributeError:
            pass
        if ok: break

    else:
        raise NotImplementedError('cannot guess format of a *%s file!' % ext)

    return format

##
# c: 05.02.2008, r: 05.02.2008
var_dict = vars().items()
io_table = {}

for key, var in var_dict:
    try:
        if is_derived_class( var, MeshIO ):
            io_table[var.format] = var
    except TypeError:
        pass
del var_dict

def any_from_filename(filename, prefix_dir=None):
    if prefix_dir is not None:
        filename = op.normpath(op.join(prefix_dir, filename))

    aux, ext = op.splitext( filename )
    ext = ext.lower()

    format = supported_formats[ext]
    if isinstance(format, tuple):
        format = guess_format( filename, ext, format, io_table )
    try:
        return io_table[format]( filename )
    except KeyError:
        output( 'unsupported mesh file suffix: %s' % ext )
        raise

insert_static_method( MeshIO, any_from_filename )
del any_from_filename
