import numpy as np
import os
import re 


class DefineParams:
    """
    Read and define fitting parameters from 
    config file

    Attributes:
    -----------
    lines, spec_path, chain_short_fname, 
    chain_fname, mcmc_outputpath: str
        Files I/O
    nwalkers, nsteps, nthreads: ints    
        MCMC parameters
    wave,flux,error: arrays
        Selected region of the input spectral data
    wave_begins, wave_ends: array_like
        Selected wavelength regions bounds
    vp_params, transitions_params_array, vp_params_type,vp_params_type:array_like
        Model auxilary parameters/controls 
    n_component: int
        Number of Components defined by the model
    lsf: array_like
        Line spread function to be convolved with the model
    priors: array_like; shape = (3,2)
        Priors for three types of parameters (logN, b, z)

    """
    
    def __init__(self,config_fname):
        self.config_fname = config_fname
        
        # Read and filter empty lines
        all_lines = filter(None,(line.rstrip() for line in open(config_fname)))

        # Remove commented lines
        self.lines = []
        for line in all_lines:
            if not line.startswith('#') and not line.startswith('!'): 
                self.lines.append(line)    

    def fileio_mcmc_params(self):
        """
        Retrieve MCMC parameters from config file

        Returns
        --------
        spec_path: path to spectrum;  
        chain_fname: full path to the chain
        nwalkers: int
            number of walkers
        nsteps: int
            number of steps per walker
        nthreads: int
            number of threads for parallelization
        """

        # Paths and fname strings
        for line in self.lines:
            line = filter(None,line.split(' '))
            if 'spec_path' in line or 'input' in line or 'spectrum' in line:
                self.spec_path = line[1]
            elif 'output' in line or 'chain' in line:
                self.chain_short_fname = line[1]
            elif 'mcmc_params' in line or 'mcmc' in line:
                self.nwalkers = int(line[1])
                self.nsteps = int(line[2])
                self.nthreads = int(line[3])

        self.mcmc_outputpath   = self.spec_path + '/vpfit_mcmc'
        if not os.path.isdir(self.mcmc_outputpath):
		    os.mkdir(self.mcmc_outputpath)
        self.chain_fname = self.mcmc_outputpath + '/' + self.chain_short_fname
 
    def fitting_data(self): 
        """
        Get the spectral data specified by the config file
        The spectrum file assumes three column of data with 
        [wave,flux,error], in that order. 

        Returns
        ---------
        wave, flux, error: array_like 
        """
        for line in self.lines: 
            if re.search('%%',line):
                spec_fname_line = line

        spec_data_array = spec_fname_line.split(' ')
        self.spec_short_fname = spec_data_array[1]
        self.spec_fname = self.spec_path + '/' + spec_data_array[1]


        # Select spectral range to fit
        if len(spec_data_array[2:]) % 2 != 0:
            print('There is odd number of wavelengths entered in config file')
            print('Exiting program...')
            exit()
        else:
            self.wave_begins = np.array(spec_data_array[2:][0::2]).astype(float)
            self.wave_ends   = np.array(spec_data_array[2:][1::2]).astype(float)

            for i in xrange(len(self.wave_begins)):
                if self.wave_begins[i] >= self.wave_ends[i]:
                    print('Starting wavelength cannot be greater or equal to ending wavelength: (%.3f, %.3f); exiting program...' % (self.wave_begins[i] ,self.wave_ends[i]))
                    exit()

        wave,flux,dflux = np.loadtxt(self.spec_fname,
                                     unpack=True,usecols=[0,1,2])
        
        # Select regions of interests 
        all_inds = []
        for i in range(len(self.wave_begins)):
            inds = np.where((wave>=self.wave_begins[i]) & (wave<self.wave_ends[i]))[0]
            all_inds.append(inds)

        all_inds   = np.hstack(np.array(all_inds))
        wave = wave[all_inds]; flux = flux[all_inds]; dflux = dflux[all_inds]
        
        # Remove NaN pixels in flux
        inds = np.where((~np.isnan(flux)))
        self.wave = wave[inds]; self.flux = flux[inds]; self.dflux = dflux[inds]

        # Set negative pixels in flux and error 
        inds = np.where((self.flux < 0)); self.flux[inds] = 0; 
        inds = np.where((self.dflux < 0)); self.dflux[inds] = 0;



    def fitting_params(self):
        """
        Get Voigt profile parameters of arbitary number of components
        specified in the config file.

        Uses './data/atom.dat' to read in atomic/transition data
        [atom state rest_wavelength oscillator_strength damping_coeff mass_amu]
        Users can add additional row to the file for new atomic data

        Returns
        --------
        vp_params: array_like
            vogit parameters 
        transitions_params_array: array_like 
        vp_params_flags
        vp_params_type
        self.n_component
        """

        amu = 1.66053892e-24   # 1 atomic mass in grams
        data_path = os.path.dirname(os.path.abspath(__file__)) # Absolute path for BayseVP
        data_file = data_path + '/data/atom.dat'
        atoms,states  = np.loadtxt(data_file, dtype=str, 
                                  unpack=True,usecols=[0,1])
        wave,osc_f,gamma,mass = np.loadtxt(data_file,unpack=True,
                                            usecols=[2,3,4,5])
        mass = mass*amu 

        def get_transitions_params(atom,state,wave_start,wave_end,redshift):

            inds = np.where((atoms == atom) & 
                            (states == state) & 
                            (wave >= wave_start/(1+redshift)) & 
                            (wave < wave_end/(1+redshift)))[0]
            if len(inds) == 0:
                return np.empty(4)*np.nan
            else:
                return np.array([osc_f[inds],wave[inds],gamma[inds], mass[inds]]).T

        # Lines in config file that contain the component parameters
        # i.e atom, state, logN, b, z
        component_lines = []
        for line in self.lines: 
            if re.search('%',line):
                component_lines.append(line)
        component_lines = component_lines[1:] 


        logNs = []; bs = []; redshifts = []
        transitions_params_array = []
        guess_alpha = []
        for i in xrange(len(component_lines)):
            line = component_lines[i]
            line = filter(None,line.split(' '))

            atom  = line[1]; state = line[2] # To obtain transition data
            logNs.append(line[3]); 
            bs.append(line[4]);
            redshifts.append(line[5])

            if line[5][-1].isalpha():
                temp_redshift = line[5][:-1]
            else:
                temp_redshift = line[5]

            transitions_params_array.append([])
            # Each component gets a set of all of the transitions data
            for j in xrange(len(self.wave_begins)):
                
                # each wavelength regions gets all of the transitions
                temp_params = get_transitions_params(atom,state,self.wave_begins[j],self.wave_ends[j],float(temp_redshift))
                transitions_params_array[i].append(temp_params)
        
        # Shape = (n_component,n_regions,n_transitions,4) 
        self.transitions_params_array = np.array(transitions_params_array)
        self.vp_params = np.array([logNs,bs,redshifts]).T
        self.n_component = len(component_lines) 


        # Define what kind of parameters to get walker initiazation ranges.
        # and for fixing and freeing paramters. 
        vp_params_type = [None]*len(self.vp_params.flatten())
        vp_params_type[::3]  = ['logN'] * (len(vp_params_type[::3]))
        vp_params_type[1::3] = ['b']    * (len(vp_params_type[1::3]))
        vp_params_type[2::3] = ['z']    * (len(vp_params_type[2::3]))
        

        flat_params = self.vp_params.flatten()
        flags = np.zeros(len(flat_params))
        free_params = np.zeros(len(flat_params))

        letters = [None]*len(flat_params)
        for i in xrange(len(flat_params)):
            for j in xrange(len(flat_params[i])):
                if flat_params[i][j].isalpha():
                    letters[i] = flat_params[i][j]
        unique_letters = filter(None,list(set(letters)))

        n_free_params_counter = 0
        for i in range(len(letters)):
            if letters[i] == None:
                flags[i] = n_free_params_counter
                n_free_params_counter += 1

        for unique_letter in unique_letters:
            inds = [i for i, x in enumerate(letters) if x == unique_letter]
            if unique_letter.islower(): 
                flags[inds] = n_free_params_counter
                n_free_params_counter += 1
            else:
                for index in inds:
                    flags[index] = None

        # Model uses these to correctly construct sets of (logN, b, z) for each component
        self.vp_params_type  = np.array(vp_params_type)
        self.vp_params_flags = np.array(flags)


    def spec_lsf(self):
        """
        Determine the LSF by specifying LSF filename with 
        'database' directory under self.spec_path.    

        Assumes LSF file contains only 1 column of data

        lsf: array_like
            Line spread function 
        """

        # Check if LSF is specified in config file
        defined_lsf = False
        for line in self.lines:
            if re.search('lsf',line) or re.search('LSF',line):
                lsf_line = line.split(' ')[1:]
                defined_lsf = True
                break

        # Get the LSF function from directory 'database'
        if defined_lsf:
            if len(lsf_line) == len(self.wave_begins):
                self.lsf = []
                for lsf_fname in lsf_line:
                    # assume lsf file has one column 
                    fname = self.spec_path + '/database/' + lsf_fname
                    self.lsf.append(np.loadtxt(fname))
            elif len(lsf_line) == 1:
                for lsf_fname in lsf_line:
                    # assume lsf file has one column 
                    fname = self.spec_path + '/database/' + lsf_fname
                    self.lsf = np.loadtxt(fname)
            else:
                print('There should be 1 LSF or the number of wavelength regions; exit program.')
                exit()
        else:
            # Convolve with LSF = 1
            self.lsf = 1.


    def priors_and_init(self):
        """
        Read priors and use them for walker 
        initialization 

        Returns 
        -----------
        format in config file:
        logN min_logN max_logN
        b    min_b    max_b
        z    mean_z   dv <----- range defined by range of velocity [km/s] 
        
        For redshift: mean_redshift dv 
        """
        self.priors = np.zeros((3,2))
        for line in self.lines:
            line = np.array(line.split(' '))
            line = filter(None,line)
            if 'logN' in line:
                self.priors[0] = [float(line[1]),float(line[2])]
            if 'b' in line:
                self.priors[1] = [float(line[1]),float(line[2])]
            if 'z' in line:
                self.priors[2] = [float(line[1]),float(line[2])]



if __name__ == '__main__':

    # test
    import sys
    from Utilities import print_config_params 
    config_fname = sys.argv[1]
    # Load config parameter object 
    obs_spec = DefineParams(config_fname)
    obs_spec.fileio_mcmc_params()
    obs_spec.fitting_data()
    obs_spec.fitting_params()
    obs_spec.spec_lsf()
    obs_spec.priors_and_init()
    
    print_config_params(obs_spec)